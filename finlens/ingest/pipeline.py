"""Ingest orchestration: pick a universe, pull it, land it.

Separate from the CLI so Airflow calls the same functions without shelling out,
and separate from the endpoint wrappers so those stay testable without touching
storage.

The scale asymmetry lives here. `ingest_structured` pulls XBRL for hundreds of
companies (cheap: one JSON document each). `ingest_text` pulls filing documents
for ten (expensive: tens of MB each, and every one has to be parsed, chunked and
embedded downstream). Both read their scope from settings rather than from
arguments, so the DAG and the CLI cannot drift apart on what "the universe" is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from finlens.config import Settings, get_settings
from finlens.identifiers import normalize_cik
from finlens.ingest import companyfacts as cf
from finlens.ingest import documents as docs
from finlens.ingest import submissions as subs
from finlens.ingest import tickers as tk
from finlens.ingest.client import EdgarClient
from finlens.ingest.landing import land_bytes, land_json
from finlens.logging import get_logger
from finlens.storage import get_store
from finlens.storage.base import (
    ObjectStore,
    companyfacts_key,
    filing_document_key,
    filing_metadata_key,
    submissions_key,
    universe_key,
)

log = get_logger(__name__)


@dataclass
class IngestReport:
    """What a run actually did. Returned rather than logged so callers can assert."""

    companies: int = 0
    submissions_landed: int = 0
    companyfacts_landed: int = 0
    documents_landed: int = 0
    skipped_no_xbrl: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def merge(self, other: IngestReport) -> IngestReport:
        self.companies += other.companies
        self.submissions_landed += other.submissions_landed
        self.companyfacts_landed += other.companyfacts_landed
        self.documents_landed += other.documents_landed
        self.skipped_no_xbrl.extend(other.skipped_no_xbrl)
        self.errors.extend(other.errors)
        return self

    def summary(self) -> str:
        return (
            f"{self.companies} companies | {self.submissions_landed} submissions | "
            f"{self.companyfacts_landed} companyfacts | {self.documents_landed} documents | "
            f"{len(self.skipped_no_xbrl)} without XBRL | {len(self.errors)} errors"
        )


def ingest_universe(
    client: EdgarClient,
    store: ObjectStore,
    *,
    when: date | None = None,
) -> list[tk.Company]:
    """Land the ticker universe and return it."""
    companies = tk.fetch_company_tickers(client)
    land_json(
        store,
        universe_key(when),
        [c.model_dump(mode="json") for c in companies],
        url=f"{client.www_url}{tk.TICKERS_PATH}",
        when=when,
    )
    return companies


def ingest_company_facts(
    client: EdgarClient,
    store: ObjectStore,
    cik: str | int,
    *,
    when: date | None = None,
    report: IngestReport | None = None,
) -> IngestReport:
    """Land one company's submissions and XBRL facts. No documents.

    This is the structured layer, and it is what runs across hundreds of
    companies: two small JSON documents each.
    """
    report = report or IngestReport()
    cik = normalize_cik(cik)
    report.companies += 1

    submissions_payload = subs.fetch_submissions(client, cik)
    if submissions_payload is None:
        report.errors.append(f"{cik}: no submissions document")
        return report

    land_json(
        store,
        submissions_key(cik, when),
        submissions_payload,
        url=subs.submissions_url(client, cik),
        when=when,
    )
    report.submissions_landed += 1

    facts_payload = cf.fetch_companyfacts(client, cik)
    if facts_payload is None:
        # Normal for smaller and foreign issuers - a fact about the company,
        # not an error in the pipeline.
        report.skipped_no_xbrl.append(cik)
    else:
        land_json(
            store,
            companyfacts_key(cik, when),
            facts_payload,
            url=cf.companyfacts_url(client, cik),
            when=when,
        )
        report.companyfacts_landed += 1

    return report


def ingest_company_documents(
    client: EdgarClient,
    store: ObjectStore,
    cik: str | int,
    settings: Settings,
    *,
    when: date | None = None,
    forms: frozenset[str] = frozenset({"10-K"}),
    max_documents: int = 5,
    report: IngestReport | None = None,
) -> IngestReport:
    """Land a company's filing documents. The expensive half.

    Requires the submissions payload, which is re-fetched rather than passed in:
    the client caches responses, so the second call is free, and coupling the
    two steps would stop either running independently.
    """
    report = report or IngestReport()
    cik = normalize_cik(cik)

    submissions_payload = subs.fetch_submissions(client, cik)
    if submissions_payload is None:
        report.errors.append(f"{cik}: no submissions document")
        return report

    filings = [
        f
        for f in subs.parse_filings(submissions_payload, cik)
        if f.form in forms
        and f.primary_document
        and f.filing_date.year >= settings.text_year_min
    ]
    # Newest first, so a partial run leaves us with the *current* filings.
    filings.sort(key=lambda f: f.filing_date, reverse=True)

    for filing in filings[:max_documents]:
        assert filing.primary_document is not None  # filtered above
        key = filing_document_key(cik, filing.accession_number, filing.primary_document)

        if store.exists(key):
            # Filing documents are immutable once published; re-fetching bytes
            # that cannot have changed is pure waste against a rate limit.
            log.debug("ingest.document_present", key=key)
            continue

        try:
            content = docs.fetch_primary_document(
                client, cik, filing.accession_number, filing.primary_document
            )
        except Exception as exc:  # noqa: BLE001 - one bad filing must not kill the run
            report.errors.append(f"{cik}/{filing.accession_number}: {exc}")
            continue
        if content is None:
            continue

        land_bytes(
            store,
            key,
            content,
            url=docs.primary_document_url(
                client, cik, filing.accession_number, filing.primary_document
            ),
            content_type="text/html",
            when=when,
        )
        # The filing's metadata travels with the document so the Spark job can
        # build section rows without re-reading the submissions payload.
        land_json(
            store,
            filing_metadata_key(cik, filing.accession_number),
            filing.model_dump(mode="json"),
            url=subs.submissions_url(client, cik),
            when=when,
        )
        report.documents_landed += 1

    return report


def ingest_structured(
    ciks: list[str] | None = None,
    settings: Settings | None = None,
    *,
    when: date | None = None,
    limit: int | None = None,
) -> IngestReport:
    """The broad layer: XBRL facts for the structured universe.

    Defaults to the largest `structured_universe_size` companies by filing
    activity, which is a rough but stable proxy for size and avoids needing a
    market-cap source EDGAR does not provide.
    """
    settings = settings or get_settings()
    settings.ensure_dirs()
    store = get_store(settings)
    report = IngestReport()

    with EdgarClient(settings) as client:
        if ciks is None:
            companies = ingest_universe(client, store, when=when)
            ciks = [c.cik for c in companies][: limit or settings.structured_universe_size]
        elif limit:
            ciks = ciks[:limit]

        for i, cik in enumerate(ciks, start=1):
            try:
                ingest_company_facts(client, store, cik, when=when, report=report)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{cik}: {exc}")
                log.error("ingest.company_failed", cik=str(cik), error=str(exc))
            if i % 25 == 0:
                log.info("ingest.progress", done=i, total=len(ciks), summary=report.summary())

    log.info("ingest.structured_complete", summary=report.summary())
    return report


def ingest_text(
    tickers: list[str] | None = None,
    settings: Settings | None = None,
    *,
    when: date | None = None,
    max_documents: int = 5,
) -> IngestReport:
    """The narrow layer: 10-K documents for the text universe."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    store = get_store(settings)
    report = IngestReport()

    wanted = [t.upper() for t in (tickers or settings.text_universe)]

    with EdgarClient(settings) as client:
        index = tk.build_ticker_index(tk.fetch_company_tickers(client))
        for ticker in wanted:
            company = index.get(ticker)
            if company is None:
                report.errors.append(f"{ticker}: not in the EDGAR ticker file")
                continue
            report.companies += 1
            try:
                ingest_company_documents(
                    client,
                    store,
                    company.cik,
                    settings,
                    when=when,
                    max_documents=max_documents,
                    report=report,
                )
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{ticker}: {exc}")
                log.error("ingest.documents_failed", ticker=ticker, error=str(exc))

    log.info("ingest.text_complete", summary=report.summary())
    return report
