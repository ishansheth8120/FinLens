"""Fetching the filing documents themselves, from ``www.sec.gov/Archives``.

The JSON APIs give us numbers; the narrative - MD&A, risk factors, the parts a
RAG index is actually for - only exists in the filing documents. Each filing's
archive directory has an ``index.json`` listing its contents, and the primary
document is named in the submissions payload.

Modern filings are inline XBRL: a single ``.htm`` that is both the human
document and the machine-readable one. Section extraction happens later, in
`finlens.spark.html_sections`; this module only fetches bytes.
"""

from __future__ import annotations

from typing import Any

from finlens.identifiers import accession_nodash, archive_dir_url, cik_int, normalize_cik
from finlens.ingest.client import EdgarClient
from finlens.ingest.models import FilingDocument
from finlens.logging import get_logger

log = get_logger(__name__)

# Forms with enough narrative to be worth indexing. 8-K is included for
# material events; the proxy (DEF 14A) for compensation and governance.
NARRATIVE_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "20-F", "40-F", "DEF 14A"})


def filing_index_url(client: EdgarClient, cik: str | int, accession: str) -> str:
    return f"{archive_dir_url(client.www_url, cik, accession)}/index.json"


def primary_document_url(
    client: EdgarClient, cik: str | int, accession: str, primary_document: str
) -> str:
    return f"{archive_dir_url(client.www_url, cik, accession)}/{primary_document}"


def list_filing_documents(
    client: EdgarClient, cik: str | int, accession: str
) -> list[FilingDocument]:
    """Every file in a filing's archive directory."""
    payload = client.get_json(filing_index_url(client, cik, accession), allow_missing=True)
    if payload is None:
        log.warning("documents.index_missing", cik=normalize_cik(cik), accession=accession)
        return []

    base = archive_dir_url(client.www_url, cik, accession)
    documents: list[FilingDocument] = []
    for item in (payload.get("directory") or {}).get("item", []):
        name = item.get("name")
        if not name or item.get("type") == "folder.gif":
            continue
        documents.append(
            FilingDocument(
                cik=normalize_cik(cik),
                accession_number=accession,
                document=name,
                doc_type=item.get("type") or None,
                size=_int_or_none(item.get("size")),
                url=f"{base}/{name}",
            )
        )
    return documents


def fetch_primary_document(
    client: EdgarClient, cik: str | int, accession: str, primary_document: str
) -> bytes | None:
    """Bytes of a filing's primary document, or ``None`` if it has moved."""
    url = primary_document_url(client, cik, accession, primary_document)
    result = client.fetch(url, allow_missing=True)
    if result is None:
        log.warning("documents.primary_missing", accession=accession, document=primary_document)
        return None
    return result.content


def full_text_url(client: EdgarClient, cik: str | int, accession: str) -> str:
    """The complete submission text file: every document concatenated.

    Large (often >10 MB) but self-contained. Useful as a fallback when the
    primary document reference in submissions is stale.
    """
    return (
        f"{client.www_url}/Archives/edgar/data/{cik_int(cik)}/"
        f"{accession_nodash(accession)}/{accession_nodash(accession)}.txt"
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
