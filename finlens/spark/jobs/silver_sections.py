"""raw/documents/**/*.htm -> silver/sections.

The bridge between the filing corpus and the RAG index: every landed primary
document is converted to text, split into items, and emitted one row per
section. Chunking and embedding happen later (`finlens.embed`) so that changing
the chunk size does not force a re-parse of tens of GB of HTML.

Each document directory also holds the ``_filing.json`` the ingest step landed
beside it, which supplies form, filing date and accession without a join back
to the submissions payload.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from finlens.config import Settings, get_settings
from finlens.logging import get_logger
from finlens.spark.html_sections import parse_filing, section_id
from finlens.storage import get_store
from finlens.storage.base import curated_key

if TYPE_CHECKING:  # pragma: no cover
    from pyspark.sql import DataFrame, SparkSession

log = get_logger(__name__)

# Below this a "section" is a heading with no body - noise in the index.
MIN_SECTION_CHARS = 200


def _metadata_for(path: str) -> dict[str, Any]:
    """Read the ``_filing.json`` sidecar next to a document.

    Executors read it directly off the shared filesystem rather than receiving
    it through a broadcast join, because the sidecar is tiny and always local
    to the document.
    """
    sidecar = Path(path.replace("file:", "")).parent / "_filing.json"
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _section_rows(row: Any) -> list[dict[str, Any]]:
    ingested_at = datetime.now(timezone.utc)
    meta = _metadata_for(row.path)
    form = meta.get("form") or "10-K"
    cik = meta.get("cik") or ""
    accession = meta.get("accession_number") or ""
    if not cik or not accession:
        return []

    filing_date = meta.get("filing_date")
    try:
        filing_dt = (
            datetime.strptime(filing_date, "%Y-%m-%d").date() if filing_date else None
        )
    except ValueError:
        filing_dt = None

    try:
        sections = parse_filing(
            bytes(row.content), form=form, min_section_chars=MIN_SECTION_CHARS
        )
    except Exception:  # noqa: BLE001 - a single unparseable filing is not fatal
        return []

    return [
        {
            "section_id": section_id(cik, accession, section.ordinal),
            "cik": cik,
            "accession_number": accession,
            "form": form,
            "filing_date": filing_dt,
            "fiscal_year": filing_dt.year if filing_dt else None,
            "item": section.item,
            "title": section.title,
            "ordinal": section.ordinal,
            "text": section.text,
            "char_count": section.char_count,
            "word_count": section.word_count,
            "source_path": row.path,
            "ingested_at": ingested_at,
        }
        for section in sections
    ]


def build(spark: SparkSession, settings: Settings) -> DataFrame:
    from finlens.spark.schemas import SECTION_SCHEMA

    source = get_store(settings).local_path("raw/documents")
    blobs = (
        spark.read.format("binaryFile")
        .option("recursiveFileLookup", "true")
        .load(source)
        .select("path", "content")
    )
    # Sidecars are metadata, not documents.
    blobs = blobs.filter(~blobs.path.endswith("_filing.json"))

    return spark.createDataFrame(blobs.rdd.flatMap(_section_rows), schema=SECTION_SCHEMA)


def run(spark: SparkSession, settings: Settings | None = None, *, mode: str = "overwrite") -> str:
    settings = settings or get_settings()
    target = get_store(settings).local_path(curated_key("silver", "sections"))

    df = build(spark, settings)
    df.write.mode(mode).partitionBy("form").parquet(target)

    log.info("silver_sections.done", target=target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", default=None)
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"])
    args = parser.parse_args()

    from finlens.spark.session import get_spark

    spark = get_spark("finlens-silver-sections", master=args.master)
    try:
        run(spark, mode=args.mode)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
