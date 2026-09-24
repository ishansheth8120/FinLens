"""raw/submissions/*.json -> bronze/filings + bronze/companies (Parquet).

One landed submissions document yields exactly one company row and many filing
rows, so both are produced in a single pass over the blobs.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from finlens.config import Settings, get_settings
from finlens.ingest.submissions import parse_company, parse_filings
from finlens.logging import get_logger
from finlens.storage import ObjectStore, get_store
from finlens.storage.base import curated_key

if TYPE_CHECKING:  # pragma: no cover
    from pyspark.sql import DataFrame, SparkSession

log = get_logger(__name__)


def _company_row(row: Any) -> list[dict[str, Any]]:
    ingested_at = datetime.now(timezone.utc)
    try:
        payload = json.loads(bytes(row.content))
        company = parse_company(payload)
    except Exception:  # noqa: BLE001
        return []
    return [
        {
            **company.model_dump(),
            "source_path": row.path,
            "ingested_at": ingested_at,
        }
    ]


def _filing_rows(row: Any) -> list[dict[str, Any]]:
    ingested_at = datetime.now(timezone.utc)
    try:
        payload = json.loads(bytes(row.content))
        filings = parse_filings(payload, payload["cik"])
    except Exception:  # noqa: BLE001
        return []
    return [
        {
            **filing.model_dump(),
            "source_path": row.path,
            "ingested_at": ingested_at,
        }
        for filing in filings
    ]


def _blobs(spark: SparkSession, settings: Settings, store: ObjectStore) -> DataFrame:
    source = store.local_path("raw/submissions")
    return (
        spark.read.format("binaryFile")
        .option("pathGlobFilter", "*.json")
        .option("recursiveFileLookup", "true")
        .load(source)
        .select("path", "content")
    )


def build(spark: SparkSession, settings: Settings, store: ObjectStore) -> tuple[DataFrame, DataFrame]:
    from finlens.spark.schemas import COMPANY_SCHEMA, FILING_SCHEMA

    blobs = _blobs(spark, settings, store)
    # Cached because both outputs consume it and the blobs are expensive to
    # re-read (one small file per company, thousands of them).
    blobs.cache()

    companies = spark.createDataFrame(blobs.rdd.flatMap(_company_row), schema=COMPANY_SCHEMA)
    filings = spark.createDataFrame(blobs.rdd.flatMap(_filing_rows), schema=FILING_SCHEMA)
    return companies, filings


def run(
    spark: SparkSession, settings: Settings | None = None, *, mode: str = "overwrite"
) -> tuple[str, str]:
    settings = settings or get_settings()
    store = get_store(settings)
    companies, filings = build(spark, settings, store)

    companies_target = store.local_path(curated_key("bronze", "companies"))
    filings_target = store.local_path(curated_key("bronze", "filings"))

    companies.coalesce(1).write.mode(mode).parquet(companies_target)
    filings.repartition(16, "cik").write.mode(mode).parquet(filings_target)

    log.info("bronze_submissions.done", companies=companies_target, filings=filings_target)
    return companies_target, filings_target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", default=None)
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"])
    args = parser.parse_args()

    from finlens.spark.session import get_spark

    spark = get_spark("finlens-bronze-submissions", master=args.master)
    try:
        run(spark, mode=args.mode)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
