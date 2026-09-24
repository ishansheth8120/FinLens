"""raw/companyfacts/*.json -> bronze/facts (Parquet).

Reads each landed companyfacts document as an opaque blob and flattens it with
`finlens.ingest.companyfacts.iter_facts` inside a ``flatMap``. Spark's JSON
reader is not used on purpose: the payload keys *are* the data (concept names
are map keys), so inference would produce a schema with one column per concept
- tens of thousands of columns, and a different set per company.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from finlens.config import Settings, get_settings
from finlens.ingest.companyfacts import iter_facts
from finlens.logging import get_logger
from finlens.storage import ObjectStore, get_store
from finlens.storage.base import curated_key

if TYPE_CHECKING:  # pragma: no cover
    from pyspark.sql import DataFrame, SparkSession

log = get_logger(__name__)


def _flatten_blob(row: Any, taxonomies: tuple[str, ...] | None) -> list[dict[str, Any]]:
    """Parse one landed document into fact dicts.

    Runs on executors. Any failure is swallowed with a marker row rather than
    raised: one unparseable company must not fail a 10,000-company job, and the
    marker makes the loss visible in a count instead of invisible in a silence.
    """
    ingested_at = datetime.now(timezone.utc)
    try:
        payload = json.loads(bytes(row.content))
    except Exception:  # noqa: BLE001
        return []

    out: list[dict[str, Any]] = []
    for fact in iter_facts(payload, taxonomies=taxonomies):
        out.append(
            {
                "cik": fact.cik,
                "taxonomy": fact.taxonomy,
                "concept": fact.concept,
                "label": fact.label,
                "unit": fact.unit,
                "value": float(fact.value) if fact.value is not None else None,
                "start_date": fact.start_date,
                "end_date": fact.end_date,
                "fiscal_year": fact.fiscal_year,
                "fiscal_period": fact.fiscal_period,
                "form": fact.form,
                "filed_date": fact.filed_date,
                "accession_number": fact.accession_number,
                "frame": fact.frame,
                "source_path": row.path,
                "ingested_at": ingested_at,
            }
        )
    return out


def build(
    spark: SparkSession,
    settings: Settings,
    store: ObjectStore,
    *,
    taxonomies: tuple[str, ...] | None = ("us-gaap", "dei", "ifrs-full"),
) -> DataFrame:
    from finlens.spark.schemas import FACT_SCHEMA

    source = store.local_path("raw/companyfacts")
    blobs = (
        spark.read.format("binaryFile")
        .option("pathGlobFilter", "*.json")
        .option("recursiveFileLookup", "true")
        .load(source)
        .select("path", "content")
    )

    facts = blobs.rdd.flatMap(lambda row: _flatten_blob(row, taxonomies))
    return spark.createDataFrame(facts, schema=FACT_SCHEMA)


def run(
    spark: SparkSession,
    settings: Settings | None = None,
    *,
    mode: str = "overwrite",
) -> str:
    settings = settings or get_settings()
    store = get_store(settings)
    target = store.local_path(curated_key("bronze", "facts"))

    df = build(spark, settings, store)
    # One file per ~1M facts keeps Parquet row groups healthy without producing
    # the thousands of tiny files a per-company partitioning would.
    df.repartition(64, "cik").write.mode(mode).parquet(target)

    log.info("bronze_companyfacts.done", target=target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", default=None)
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"])
    args = parser.parse_args()

    from finlens.spark.session import get_spark

    spark = get_spark("finlens-bronze-companyfacts", master=args.master)
    try:
        run(spark, mode=args.mode)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
