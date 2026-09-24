"""Nightly eval against the golden set.

Runs after the ingest DAG so it measures the system as it will be served the
next morning. The point is regression detection: a prompt change, a model
change, or a data change that quietly degrades routing shows up here rather
than in a user's answer.

Compares against the last recorded run and fails on a *case-level* regression
rather than on a headline number moving - aggregate scores drift by a point or
two run to run, and a gate that fires on that noise gets muted within a week.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.decorators import dag, task
from airflow.models import Variable

DEFAULT_ARGS = {
    "owner": "finlens",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
}


@dag(
    dag_id="finlens_nightly_eval",
    description="Run the golden set and gate on regressions",
    schedule="0 4 * * 2-6",  # after the weekday ingest run
    start_date=pendulum.datetime(2026, 1, 1, tz="America/New_York"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["finlens", "eval"],
    doc_md=__doc__,
)
def finlens_nightly_eval():
    @task
    def run_golden_set() -> str:
        from finlens.eval.harness import run_eval

        report = run_eval(with_judge=True, save=True)
        print(report.to_markdown())
        return report.run_id

    @task
    def gate(run_id: str) -> None:
        """Fail the DAG if any previously-passing case now fails."""
        from finlens.eval.harness import compare_runs

        baseline = Variable.get("finlens_eval_baseline", default_var="")
        if not baseline:
            Variable.set("finlens_eval_baseline", run_id)
            print(f"no baseline recorded; {run_id} is now the baseline")
            return

        diff = compare_runs(baseline, run_id)
        cases = diff["_cases"]

        for metric, values in diff.items():
            if metric != "_cases":
                print(f"{metric}: {values['baseline']:.3f} -> {values['candidate']:.3f}")

        if cases["fixed"]:
            print(f"fixed: {cases['fixed']}")

        if cases["regressed"]:
            raise ValueError(
                f"{len(cases['regressed'])} cases regressed against {baseline}: "
                f"{cases['regressed']}"
            )

        # Only advance the baseline on a clean run, so a regression is measured
        # against the last known-good state rather than against yesterday's
        # already-degraded one.
        Variable.set("finlens_eval_baseline", run_id)
        print(f"clean run; baseline advanced to {run_id}")

    gate(run_golden_set())


finlens_nightly_eval()
