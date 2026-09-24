"""bronze/facts -> silver/facts.

Three derivations happen here, and each one exists because skipping it produces
a plausible-looking wrong number:

**Period classification.** XBRL mixes instants (a balance) with durations
(a flow), and mixes 3-month, 6-month, 9-month and 12-month durations inside the
same concept. A query that sums "quarterly revenue" without filtering on
duration length double-counts Q1 into the year-to-date figures. ``period_kind``
makes that filterable.

**Restatement ranking.** The same (concept, period) is reported by every filing
that touches it. ``is_latest`` marks the most recently filed version;
``restatement_count`` and ``value_changed`` expose the ones that moved, which is
itself an interesting signal.

**Fiscal alignment.** ``fy``/``fp`` as reported are the *filing's* fiscal
context, not the fact's - a FY2024 10-K carries FY2022 comparatives tagged
``fy=2024``. The calendar fields derived from ``end_date`` are what comparisons
across companies with different year ends must use.
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

# Tolerances around nominal period lengths. A "quarter" filed as 89 or 92 days
# is still a quarter; 180 days is not.
PERIOD_BUCKETS = [
    ("quarterly", 80, 100),
    ("half_year", 170, 190),
    ("three_quarters", 260, 285),
    ("annual", 350, 380),
]


def build(spark: SparkSession, settings: Settings) -> DataFrame:
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    facts = spark.read.parquet(get_store(settings).local_path(curated_key("bronze", "facts")))

    # --- period shape --------------------------------------------------------
    facts = facts.withColumn(
        "period_type",
        F.when(F.col("start_date").isNull(), F.lit("instant")).otherwise(F.lit("duration")),
    ).withColumn(
        "duration_days",
        F.when(
            F.col("start_date").isNotNull(),
            F.datediff(F.col("end_date"), F.col("start_date")),
        ),
    )

    period_kind = F.when(F.col("period_type") == "instant", F.lit("instant"))
    for name, low, high in PERIOD_BUCKETS:
        period_kind = period_kind.when(
            F.col("duration_days").between(low, high), F.lit(name)
        )
    facts = facts.withColumn("period_kind", period_kind.otherwise(F.lit("irregular")))

    # --- calendar alignment --------------------------------------------------
    facts = (
        facts.withColumn("calendar_year", F.year("end_date"))
        .withColumn("calendar_quarter", F.quarter("end_date"))
        .withColumn(
            "calendar_period",
            F.concat_ws("", F.lit("CY"), F.year("end_date").cast("string"),
                        F.lit("Q"), F.quarter("end_date").cast("string")),
        )
    )

    # --- restatement ranking -------------------------------------------------
    fact_key = ["cik", "taxonomy", "concept", "unit", "start_date", "end_date"]
    # filed_date can be null for frame-sourced facts; nulls_last keeps a dated
    # filing ahead of an undated one rather than letting null win the ordering.
    recency = Window.partitionBy(*fact_key).orderBy(
        F.col("filed_date").desc_nulls_last(), F.col("accession_number").desc_nulls_last()
    )
    whole_key = Window.partitionBy(*fact_key)

    facts = (
        facts.withColumn("report_rank", F.row_number().over(recency))
        .withColumn("is_latest", F.col("report_rank") == 1)
        .withColumn("restatement_count", F.count(F.lit(1)).over(whole_key) - 1)
        .withColumn("distinct_values", F.size(F.collect_set("value").over(whole_key)))
        .withColumn("value_changed", F.col("distinct_values") > 1)
        .drop("distinct_values")
    )

    # --- surrogate key -------------------------------------------------------
    # Deterministic so a rebuild produces identical keys and dbt snapshots stay
    # stable. Includes the accession because restatements are distinct rows.
    facts = facts.withColumn(
        "fact_sk",
        F.sha2(
            F.concat_ws(
                "|",
                *[F.coalesce(F.col(c).cast("string"), F.lit("")) for c in fact_key],
                F.coalesce(F.col("accession_number"), F.lit("")),
            ),
            256,
        ),
    )

    return facts.filter(F.col("value").isNotNull())


def run(spark: SparkSession, settings: Settings | None = None, *, mode: str = "overwrite") -> str:
    settings = settings or get_settings()
    target = get_store(settings).local_path(curated_key("silver", "facts"))

    df = build(spark, settings)
    # Partitioned by calendar year because essentially every downstream query
    # filters on a period, and by taxonomy because us-gaap dwarfs the rest.
    df.write.mode(mode).partitionBy("taxonomy", "calendar_year").parquet(target)

    log.info("silver_facts.done", target=target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", default=None)
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"])
    args = parser.parse_args()

    from finlens.spark.session import get_spark

    spark = get_spark("finlens-silver-facts", master=args.master)
    try:
        run(spark, mode=args.mode)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
