"""Historical backfill, one slice of the universe per run.

Separate from the daily DAG because it has opposite characteristics: it runs for
hours, it must be resumable, and it must never contend with the daily run for
SEC's rate budget. The shared `edgar_rate_limit` pool with one slot enforces the
last of those - the two DAGs can be scheduled overlapping and will still present
a single request stream to SEC.

Trigger with a config payload:

    {"batch_size": 200, "offset": 0, "include_text": false}

The final task prints the next offset, so chaining runs is mechanical.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.decorators import dag, task

DEFAULT_ARGS = {
    "owner": "finlens",
    "retries": 3,
    "retry_delay": timedelta(minutes=30),
    "email_on_failure": False,
}


@dag(
    dag_id="finlens_backfill",
    description="Backfill EDGAR history for a slice of the company universe",
    schedule=None,  # manual trigger only
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["finlens", "backfill"],
    doc_md=__doc__,
    params={"batch_size": 200, "offset": 0, "include_text": False},
)
def finlens_backfill():
    @task
    def universe_slice(**context) -> list[str]:
        """The CIKs this run covers.

        Lands the universe file as a side effect, which is what makes the
        slicing stable across runs - the ordering comes from a snapshot in the
        lake rather than from a fresh fetch each time.
        """
        from finlens.config import get_settings
        from finlens.ingest.client import EdgarClient
        from finlens.ingest.pipeline import ingest_universe
        from finlens.storage import get_store

        params = context["params"]
        settings = get_settings()
        settings.ensure_dirs()
        store = get_store(settings)

        with EdgarClient(settings) as client:
            companies = ingest_universe(client, store)

        ciks = [c.cik for c in companies]
        offset, batch_size = int(params["offset"]), int(params["batch_size"])
        slice_ = ciks[offset : offset + batch_size]

        print(f"universe={len(ciks)} slice=[{offset}:{offset + batch_size}] -> {len(slice_)} CIKs")
        return slice_

    @task(
        # One slot, shared with the daily DAG: two concurrent request streams
        # to SEC is what gets an IP blocked.
        pool="edgar_rate_limit",
        execution_timeout=timedelta(hours=12),
    )
    def backfill_structured(ciks: list[str]) -> dict[str, int]:
        from finlens.ingest.pipeline import ingest_structured

        report = ingest_structured(list(ciks))
        print(report.summary())
        return {
            "companies": report.companies,
            "companyfacts": report.companyfacts_landed,
            "no_xbrl": len(report.skipped_no_xbrl),
            "errors": len(report.errors),
        }

    @task(pool="edgar_rate_limit", execution_timeout=timedelta(hours=6))
    def backfill_text(**context) -> dict[str, int]:
        """Filing documents, only when explicitly asked for.

        Off by default: the text universe is fixed at ten companies by design,
        so a structured backfill has no text component to extend.
        """
        params = context["params"]
        if not params["include_text"]:
            print("include_text is false - skipping the text layer")
            return {"documents": 0}

        from finlens.ingest.pipeline import ingest_text

        report = ingest_text(max_documents=10)
        print(report.summary())
        return {"companies": report.companies, "documents": report.documents_landed}

    @task
    def report_progress(structured: dict[str, int], text: dict[str, int], **context) -> None:
        params = context["params"]
        next_offset = int(params["offset"]) + int(params["batch_size"])
        print(f"structured: {structured}")
        print(f"text:       {text}")
        print(f"next run:   trigger with offset={next_offset}")

    ciks = universe_slice()
    report_progress(backfill_structured(ciks), backfill_text())


finlens_backfill()
