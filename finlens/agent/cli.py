"""``finlens-ask`` - ask the agent a question from the terminal."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from finlens.agent.orchestrator import Agent
from finlens.agent.router import route as route_question
from finlens.agent.schema_catalog import get_catalog_text
from finlens.agent.types import Route
from finlens.logging import configure_logging

app = typer.Typer(add_completion=False, help="Ask FinLens a question about SEC filings.")


@app.callback()
def _init() -> None:
    configure_logging()


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="Your question")],
    route: Annotated[str | None, typer.Option(help="Force sql | rag | hybrid")] = None,
    show_sql: Annotated[bool, typer.Option(help="Print the generated SQL")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit the full Answer as JSON")] = False,
) -> None:
    """Answer a question."""
    forced = Route(route) if route else None

    with Agent() as agent:
        answer = agent.ask(question, force_route=forced)

    if as_json:
        typer.echo(answer.model_dump_json(indent=2))
        return

    typer.echo(f"\n{answer.answer}\n")

    if answer.citations:
        typer.echo("Sources:")
        for i, citation in enumerate(answer.citations, start=1):
            typer.echo(f"  [{i}] {citation.label}")

    if show_sql and answer.sql_result and answer.sql_result.sql:
        typer.echo(f"\nSQL:\n{answer.sql_result.sql}")

    for warning in answer.warnings:
        typer.echo(f"\n! {warning}", err=True)

    typer.echo(
        f"\nroute={answer.route.value} "
        f"tokens={answer.usage.input_tokens + answer.usage.output_tokens} "
        f"cache_read={answer.usage.cache_read_tokens} "
        f"{answer.elapsed_ms:.0f}ms"
    )


@app.command("route")
def route_only(question: Annotated[str, typer.Argument(help="Your question")]) -> None:
    """Show the routing decision without answering. Useful when debugging the eval."""
    decision, usage = route_question(question)
    typer.echo(decision.model_dump_json(indent=2))
    typer.echo(f"\ntokens={usage.input_tokens + usage.output_tokens}", err=True)


@app.command()
def schema() -> None:
    """Print the schema catalogue exactly as the SQL generator sees it."""
    typer.echo(get_catalog_text())


@app.command()
def explain(question: Annotated[str, typer.Argument(help="Your question")]) -> None:
    """Answer, then dump every intermediate stage as JSON."""
    with Agent() as agent:
        answer = agent.ask(question)

    payload = {
        "route": answer.route.value,
        "reasoning": answer.reasoning,
        "sql": answer.sql_result.sql if answer.sql_result else None,
        "sql_error": answer.sql_result.error if answer.sql_result else None,
        "row_count": answer.sql_result.row_count if answer.sql_result else 0,
        "retrieved": len(answer.retrieval.citations) if answer.retrieval else 0,
        "citations": [c.label for c in answer.citations],
        "warnings": answer.warnings,
        "usage": answer.usage.model_dump(),
        "elapsed_ms": round(answer.elapsed_ms, 1),
    }
    typer.echo(json.dumps(payload, indent=2))
    typer.echo(f"\n{answer.answer}")


if __name__ == "__main__":
    app()
