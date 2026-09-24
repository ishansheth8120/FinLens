"""``finlens-embed`` - build and inspect the vector index."""

from __future__ import annotations

from typing import Annotated

import typer

from finlens.config import get_settings
from finlens.embed.index import build_index
from finlens.embed.providers import get_provider
from finlens.embed.store import Filters, VectorStore
from finlens.logging import configure_logging

app = typer.Typer(add_completion=False, help="Chunk, embed and search filing text.")


@app.callback()
def _init() -> None:
    configure_logging()


@app.command()
def build(
    forms: Annotated[list[str] | None, typer.Option(help="Restrict to form types")] = None,
    since: Annotated[int | None, typer.Option(help="Minimum fiscal year")] = None,
    limit: Annotated[int | None, typer.Option(help="Cap sections, for a smoke test")] = None,
    rebuild: Annotated[bool, typer.Option(help="Drop the index before building")] = False,
) -> None:
    """Build the index from `marts.fct_filing_section`."""
    report = build_index(
        forms=list(forms) if forms else None,
        fiscal_year_min=since,
        limit=limit,
        rebuild=rebuild,
    )
    typer.echo(report.summary())


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Natural-language query")],
    top_k: Annotated[int, typer.Option(help="Results to return")] = 8,
    ticker: Annotated[list[str] | None, typer.Option(help="Restrict to tickers")] = None,
    form: Annotated[list[str] | None, typer.Option(help="Restrict to form types")] = None,
    mode: Annotated[str, typer.Option(help="hybrid | dense | keyword")] = "hybrid",
) -> None:
    """Search the index directly, bypassing the agent."""
    settings = get_settings()
    provider = get_provider(settings)
    filters = Filters(
        tickers=[t.upper() for t in ticker] if ticker else None,
        forms=list(form) if form else None,
    )

    with VectorStore(dim=provider.dim, settings=settings, read_only=True) as store:
        if mode == "keyword":
            hits = store.keyword_search(query, top_k=top_k, filters=filters)
        else:
            vector = provider.embed_one(query, input_type="query")
            hits = (
                store.vector_search(vector, top_k=top_k, filters=filters)
                if mode == "dense"
                else store.hybrid_search(query, vector, top_k=top_k, filters=filters)
            )

    if not hits:
        typer.echo("no results - is the index built?")
        raise typer.Exit(code=1)

    for rank, hit in enumerate(hits, start=1):
        typer.echo(f"\n[{rank}] {hit.citation}  (score {hit.score:.4f})")
        typer.echo(f"    {hit.text[:300].strip()}...")


@app.command()
def stats() -> None:
    """Index size and provider configuration."""
    settings = get_settings()
    with VectorStore(settings=settings, read_only=True) as store:
        count = store.count()
    typer.echo(f"chunks:   {count:,}")
    typer.echo(f"provider: {settings.embedding_provider} ({settings.embedding_model})")
    typer.echo(f"dim:      {settings.embedding_dim}")
    typer.echo(f"path:     {store.path}")


if __name__ == "__main__":
    app()
