"""``finlens-eval`` - run the golden set, inspect and compare runs."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from finlens.agent.types import Route
from finlens.eval.golden import Difficulty, filter_cases, load_golden_set
from finlens.eval.harness import RUNS_DIR, compare_runs, load_report, run_eval
from finlens.logging import configure_logging

app = typer.Typer(add_completion=False, help="Evaluate FinLens against the golden set.")


@app.callback()
def _init() -> None:
    configure_logging()


@app.command()
def run(
    tags: Annotated[list[str] | None, typer.Option(help="Only cases with these tags")] = None,
    route: Annotated[list[str] | None, typer.Option(help="Only these expected routes")] = None,
    difficulty: Annotated[str | None, typer.Option(help="easy | medium | hard")] = None,
    case_id: Annotated[list[str] | None, typer.Option("--id", help="Specific case ids")] = None,
    judge: Annotated[bool, typer.Option(help="Run the LLM judge")] = True,
    save: Annotated[bool, typer.Option(help="Persist the run")] = True,
) -> None:
    """Run the golden set."""
    cases = filter_cases(
        load_golden_set(),
        tags=list(tags) if tags else None,
        routes=[Route(r) for r in route] if route else None,
        difficulty=Difficulty(difficulty) if difficulty else None,
        ids=list(case_id) if case_id else None,
    )
    if not cases:
        typer.echo("no cases matched the filters", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"running {len(cases)} cases...\n")
    report = run_eval(cases, with_judge=judge, save=save)
    typer.echo(report.to_markdown())

    pass_rate = report.summary.get("pass_rate")
    if pass_rate is not None and pass_rate < 1.0:
        raise typer.Exit(code=1)


@app.command("list")
def list_cases(
    tags: Annotated[list[str] | None, typer.Option(help="Filter by tag")] = None,
) -> None:
    """List the golden set."""
    cases = filter_cases(load_golden_set(), tags=list(tags) if tags else None)
    for case in cases:
        typer.echo(
            f"{case.id:<38} {case.expected_route.value:<9} "
            f"{case.difficulty.value:<7} {case.question[:60]}"
        )
    typer.echo(f"\n{len(cases)} cases")


@app.command()
def show(run_id: Annotated[str, typer.Argument(help="Run id, e.g. 20260912T101500Z")]) -> None:
    """Print a saved run's report."""
    report = load_report(run_id)
    typer.echo(json.dumps(report["summary"], indent=2))
    typer.echo("\nCaveats:")
    for caveat in report.get("caveats", []) or ["(none)"]:
        typer.echo(f"  - {caveat}")


@app.command()
def runs() -> None:
    """List saved runs, newest first."""
    if not RUNS_DIR.exists():
        typer.echo("no runs yet")
        return
    for path in sorted(RUNS_DIR.iterdir(), reverse=True):
        if not (path / "report.json").exists():
            continue
        summary = json.loads((path / "report.json").read_text())["summary"]
        pass_rate = summary.get("pass_rate")
        typer.echo(
            f"{path.name}  cases={summary.get('cases', 0):<4} "
            f"pass={pass_rate if pass_rate is None else f'{pass_rate:.2f}'}"
        )


@app.command()
def compare(
    baseline: Annotated[str, typer.Argument(help="Baseline run id")],
    candidate: Annotated[str, typer.Argument(help="Candidate run id")],
) -> None:
    """Diff two runs. Exits non-zero if any case regressed."""
    diff = compare_runs(baseline, candidate)
    cases = diff.pop("_cases")

    typer.echo(f"{'metric':<32} {'baseline':>10} {'candidate':>10} {'delta':>9}")
    for metric, values in diff.items():
        typer.echo(
            f"{metric:<32} {values['baseline']:>10.3f} "
            f"{values['candidate']:>10.3f} {values['delta']:>+9.3f}"
        )

    if cases["fixed"]:
        typer.echo(f"\nfixed:     {', '.join(cases['fixed'])}")
    if cases["regressed"]:
        typer.echo(f"regressed: {', '.join(cases['regressed'])}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
