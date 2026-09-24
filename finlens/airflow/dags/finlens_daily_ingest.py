"""Daily incremental ingest: new filings -> lake -> warehouse -> index.

Scheduled on weekday evenings US Eastern. EDGAR accepts filings until 17:30 ET
and publishes through the evening, so an overnight run picks up a full day.

The two ingest tasks are separate because the layers have genuinely different
costs (see docs/ARCHITECTURE.md §3): the structured pull is hundreds of small
JSON documents, the text pull is ten companies of large HTML. Splitting them
means the expensive half can fail or be skipped without losing the cheap half.

The DAG is deliberately sequential rather than fanned out per company. The
bottleneck is SEC's rate limit, not our compute, and parallel tasks would each
hold their own limiter and collectively breach it - which gets the source IP
blocked for hours.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pendulum
from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.operators.bash import BashOperator

DEFAULT_ARGS = {
    "owner": "finlens",
    "retries": 2,
    "retry_delay": timedelta(minutes=15),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(hours=1),
    "email_on_failure": False,
}


@dag(
    dag_id="finlens_daily_ingest",
    description="Pull new EDGAR filings, rebuild the warehouse, refresh the index",
    schedule="0 22 * * 1-5",
    start_date=pendulum.datetime(2026, 1, 1, tz="America/New_York"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["finlens", "ingest"],
    doc_md=__doc__,
)
def finlens_daily_ingest():
    @task(pool="edgar_rate_limit")
    def ingest_structured_layer() -> dict[str, int]:
        """XBRL facts for the structured universe. The broad, cheap layer.

        The watchlist is an Airflow Variable so it can change without a deploy;
        absent one, the configured universe size applies.
        """
        from finlens.ingest.pipeline import ingest_structured

        watchlist = Variable.get("finlens_watchlist", default_var="")
        tickers = [t.strip().upper() for t in watchlist.split(",") if t.strip()] or None

        report = ingest_structured(tickers)
        if report.errors:
            # Partial failure is normal - a delisted company, a moved document -
            # and should not fail the run, but it must be visible.
            print(f"{len(report.errors)} errors; first few: {report.errors[:5]}")
        return {
            "companies": report.companies,
            "submissions": report.submissions_landed,
            "companyfacts": report.companyfacts_landed,
            "no_xbrl": len(report.skipped_no_xbrl),
        }

    @task(pool="edgar_rate_limit")
    def ingest_text_layer() -> dict[str, int]:
        """10-K documents for the text universe. The narrow, expensive layer.

        Already-landed documents are skipped: filing bytes are immutable once
        published, so re-fetching them is pure waste against the rate limit.
        """
        from finlens.ingest.pipeline import ingest_text

        report = ingest_text(max_documents=2)
        return {"companies": report.companies, "documents": report.documents_landed}

    spark_bronze = BashOperator(
        task_id="spark_bronze",
        bash_command=(
            "set -e\n"
            "spark-submit --master ${SPARK_MASTER:-local[*]} "
            "  -m finlens.spark.jobs.bronze_submissions\n"
            "spark-submit --master ${SPARK_MASTER:-local[*]} "
            "  -m finlens.spark.jobs.bronze_companyfacts"
        ),
    )

    spark_silver = BashOperator(
        task_id="spark_silver",
        bash_command=(
            "set -e\n"
            "spark-submit --master ${SPARK_MASTER:-local[*]} "
            "  -m finlens.spark.jobs.silver_entities\n"
            "spark-submit --master ${SPARK_MASTER:-local[*]} "
            "  -m finlens.spark.jobs.silver_facts\n"
            "spark-submit --master ${SPARK_MASTER:-local[*]} "
            "  -m finlens.spark.jobs.silver_sections"
        ),
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        # `dbt build` interleaves models and their tests, so a model whose test
        # fails does not silently feed the models downstream of it.
        bash_command=(
            "cd ${FINLENS_DBT_DIR:-/opt/finlens/finlens/warehouse} && "
            "dbt seed --target ${FINLENS_DBT_TARGET:-dev} && "
            "dbt build --target ${FINLENS_DBT_TARGET:-dev} && "
            # The manifest is what the text-to-SQL prompt reads its column
            # descriptions from. Stale manifest, stale prompt, worse SQL.
            "dbt docs generate --target ${FINLENS_DBT_TARGET:-dev}"
        ),
    )

    @task
    def refresh_index() -> dict[str, int]:
        """Chunk and embed sections not already in the index."""
        from finlens.embed.index import build_index

        report = build_index(rebuild=False)
        return {"sections": report.sections, "chunks": report.chunks, "embedded": report.embedded}

    @task
    def freshness_check() -> None:
        """Fail loudly if the pipeline ran but produced nothing new.

        A green DAG over a stale warehouse is the worst outcome: everything
        downstream keeps serving yesterday's answers with today's confidence.
        """
        import duckdb

        from finlens.config import get_settings

        settings = get_settings()
        con = duckdb.connect(str(settings.duckdb_path), read_only=True)
        try:
            latest = con.execute("SELECT max(filing_date) FROM marts.dim_filing").fetchone()[0]
        finally:
            con.close()

        if latest is None:
            raise ValueError("dim_filing is empty after a successful build")

        age_days = (datetime.now().date() - latest).days
        if age_days > 7:
            raise ValueError(f"newest filing is {age_days} days old - ingest is not keeping up")
        print(f"newest filing: {latest} ({age_days}d old)")

    structured = ingest_structured_layer()
    text = ingest_text_layer()

    # Both ingest layers must land before Spark reads the lake, but they are
    # independent of each other and share the rate-limit pool rather than a
    # dependency edge.
    [structured, text] >> spark_bronze >> spark_silver >> dbt_build
    dbt_build >> refresh_index() >> freshness_check()


finlens_daily_ingest()
