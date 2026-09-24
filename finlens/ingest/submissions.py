"""Company submission history - ``data.sec.gov/submissions/CIK##########.json``.

The payload is columnar and paginated in an unusual way: ``filings.recent``
holds roughly the last 1,000 filings inline, and anything older is split into
separate files listed under ``filings.files``. Ignoring that second list is the
classic way to silently lose a company's history before ~2018.
"""

from __future__ import annotations

from typing import Any

from finlens.identifiers import normalize_cik
from finlens.ingest.client import EdgarClient
from finlens.ingest.models import Company, Filing
from finlens.logging import get_logger

log = get_logger(__name__)


def submissions_url(client: EdgarClient, cik: str | int) -> str:
    return f"{client.data_url}/submissions/CIK{normalize_cik(cik)}.json"


def fetch_submissions(client: EdgarClient, cik: str | int) -> dict[str, Any] | None:
    """Raw submissions payload, or ``None`` if the CIK has no filings."""
    return client.get_json(submissions_url(client, cik), allow_missing=True)


def parse_company(payload: dict[str, Any]) -> Company:
    return Company(
        cik=payload["cik"],
        ticker=(payload.get("tickers") or [None])[0],
        name=payload.get("name", ""),
        exchange=(payload.get("exchanges") or [None])[0],
        sic=payload.get("sic") or None,
        sic_description=payload.get("sicDescription") or None,
        fiscal_year_end=payload.get("fiscalYearEnd") or None,
        state_of_incorporation=payload.get("stateOfIncorporation") or None,
    )


def parse_filings(payload: dict[str, Any], cik: str | int) -> list[Filing]:
    """Flatten the columnar ``filings.recent`` block into `Filing` rows."""
    recent = (payload.get("filings") or {}).get("recent") or {}
    return _rows_from_columns(recent, cik)


def older_filing_files(payload: dict[str, Any]) -> list[str]:
    """Names of the overflow files holding filings older than ``recent``."""
    files = (payload.get("filings") or {}).get("files") or []
    return [f["name"] for f in files if f.get("name")]


def fetch_all_filings(client: EdgarClient, cik: str | int) -> list[Filing]:
    """Complete filing history: ``recent`` plus every overflow file."""
    payload = fetch_submissions(client, cik)
    if payload is None:
        log.info("submissions.absent", cik=normalize_cik(cik))
        return []

    filings = parse_filings(payload, cik)
    for name in older_filing_files(payload):
        older = client.get_json(f"{client.data_url}/submissions/{name}", allow_missing=True)
        if older:
            filings.extend(_rows_from_columns(older, cik))

    log.info("submissions.fetched", cik=normalize_cik(cik), filings=len(filings))
    return filings


def _rows_from_columns(block: dict[str, Any], cik: str | int) -> list[Filing]:
    """Transpose EDGAR's parallel-arrays layout into records.

    Every column is meant to be the same length; if SEC ever ships a ragged
    payload we truncate to the shortest rather than raise, because a partial
    history is far more useful than none.
    """
    accessions = block.get("accessionNumber") or []
    if not accessions:
        return []

    columns = {
        key: block.get(key) or []
        for key in (
            "accessionNumber",
            "form",
            "filingDate",
            "reportDate",
            "acceptanceDateTime",
            "primaryDocument",
            "primaryDocDescription",
            "items",
            "size",
            "isXBRL",
            "isInlineXBRL",
        )
    }
    n = min(len(v) for v in columns.values() if v)

    rows: list[Filing] = []
    for i in range(n):
        rows.append(
            Filing(
                cik=cik,
                accession_number=columns["accessionNumber"][i],
                form=columns["form"][i],
                filing_date=columns["filingDate"][i],
                report_date=_at(columns["reportDate"], i),
                acceptance_datetime=_at(columns["acceptanceDateTime"], i),
                primary_document=_at(columns["primaryDocument"], i),
                primary_doc_description=_at(columns["primaryDocDescription"], i),
                items=_at(columns["items"], i),
                size=_at(columns["size"], i),
                is_xbrl=bool(_at(columns["isXBRL"], i)),
                is_inline_xbrl=bool(_at(columns["isInlineXBRL"], i)),
            )
        )
    return rows


def _at(column: list[Any], i: int) -> Any:
    return column[i] if i < len(column) else None
