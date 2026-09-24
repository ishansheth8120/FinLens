"""Spark session construction.

Defaults are tuned for the two shapes this project runs in: a laptop reading a
few hundred companies, and a cluster reading the full universe. The settings
that matter for both are here rather than in `spark-submit` flags, so a job
behaves the same however it is launched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from pyspark.sql import SparkSession

DEFAULT_CONF: dict[str, str] = {
    # EDGAR JSON is many small-to-medium files; the default 128MB target
    # produces a handful of huge tasks and idle executors.
    "spark.sql.files.maxPartitionBytes": "33554432",  # 32 MB
    "spark.sql.shuffle.partitions": "64",
    # Adaptive execution coalesces the many tiny output partitions the fact
    # explode produces, which otherwise writes thousands of small Parquet files.
    "spark.sql.adaptive.enabled": "true",
    "spark.sql.adaptive.coalescePartitions.enabled": "true",
    # Parquet timestamps: keep them comparable with DuckDB and dbt.
    "spark.sql.parquet.outputTimestampType": "TIMESTAMP_MICROS",
    "spark.sql.session.timeZone": "UTC",
    # Fail rather than silently null out a malformed date - a wrong date here
    # becomes a wrong fiscal period in every downstream metric.
    "spark.sql.ansi.enabled": "false",
    "spark.sql.legacy.timeParserPolicy": "CORRECTED",
    "spark.serializer": "org.apache.spark.serializer.KryoSerializer",
}


def get_spark(
    app_name: str = "finlens",
    *,
    master: str | None = None,
    conf: dict[str, str] | None = None,
) -> SparkSession:
    """Build (or attach to) a Spark session.

    ``master`` defaults to whatever the environment provides, so the same call
    works under ``spark-submit`` on a cluster and bare ``python`` locally.
    """
    from pyspark.sql import SparkSession

    builder = SparkSession.builder.appName(app_name)
    if master:
        builder = builder.master(master)
    for key, value in {**DEFAULT_CONF, **(conf or {})}.items():
        builder = builder.config(key, value)

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
