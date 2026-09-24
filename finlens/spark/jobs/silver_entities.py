"""bronze/companies + bronze/filings -> silver/companies + silver/filings.

Deduplication only, but non-trivial deduplication: the raw zone is append-only
and partitioned by ingest date, so a company pulled weekly has one bronze row
per pull. Keeping the newest by ``ingested_at`` gives a current-state table;
the history is still in the lake if anyone wants it.
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from finlens.config import Settings, get_settings
from finlens.logging import get_logger
from finlens.storage import get_store
from finlens.storage.base import curated_key

if TYPE_CHECKING:  # pragma: no cover
    from pyspark.sql import DataFrame, SparkSession

log = get_logger(__name__)


def _latest_per_key(df: DataFrame, keys: list[str]) -> DataFrame:
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    window = Window.partitionBy(*keys).orderBy(F.col("ingested_at").desc())
    return (
        df.withColumn("_rn", F.row_number().over(window)).filter(F.col("_rn") == 1).drop("_rn")
    )


def build(spark: SparkSession, settings: Settings) -> tuple[DataFrame, DataFrame]:
    from pyspark.sql import functions as F

    store = get_store(settings)

    companies = _latest_per_key(
        spark.read.parquet(store.local_path(curated_key("bronze", "companies"))), ["cik"]
    )
    filings = _latest_per_key(
        spark.read.parquet(store.local_path(curated_key("bronze", "filings"))),
        ["cik", "accession_number"],
    )

    # An amendment supersedes the filing it amends for "what is current", but
    # both stay in the table - flagged, not deleted, because "what did the
    # original say" is a legitimate question.
    filings = filings.withColumn("is_amendment", F.col("form").endswith("/A")).withColumn(
        "base_form", F.regexp_replace(F.col("form"), r"/A$", "")
    )

    return companies, filings


def run(
    spark: SparkSession, settings: Settings | None = None, *, mode: str = "overwrite"
) -> tuple[str, str]:
    settings = settings or get_settings()
    companies, filings = build(spark, settings)

    store = get_store(settings)
    companies_target = store.local_path(curated_key("silver", "companies"))
    filings_target = store.local_path(curated_key("silver", "filings"))

    companies.coalesce(1).write.mode(mode).parquet(companies_target)
    filings.repartition(8).write.mode(mode).parquet(filings_target)

    log.info("silver_entities.done", companies=companies_target, filings=filings_target)
    return companies_target, filings_target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", default=None)
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"])
    args = parser.parse_args()

    from finlens.spark.session import get_spark

    spark = get_spark("finlens-silver-entities", master=args.master)
    try:
        run(spark, mode=args.mode)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
