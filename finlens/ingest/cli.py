"""``finlens-ingest`` - pull EDGAR data into the raw zone.

The two layers are separate commands because they have genuinely different
costs. `structured` is hundreds of companies of small JSON; `text` is ten
companies of large HTML. Running them together would hide that, and the scale
asymmetry is a deliberate design decision, not an accident of scheduling.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from finlens.config import get_settings
from finlens.identifiers import normalize_cik
from finlens.ingest import companyfacts as cf
from finlens.ingest import frames as fr
from finlens.ingest import tickers as tk
from finlens.ingest.client import EdgarClient
from finlens.ingest.landing import land_json
from finlens.ingest.pipeline import ingest_structured, ingest_text, ingest_universe
from finlens.logging import configure_logging, get_logger
from finlens.storage import get_store

app = typer.Typer(add_completion=False, help="Pull SEC EDGAR data into the FinLens lake.")
log = get_logger(__name__)


@app.callback()
def _init() -> None:
    configure_logging()


@app.command()
def universe() -> None:
    """Land the ticker -> CIK universe."""
    settings = get_settings()
    settings.ensure_dirs()
    store = get_store(settings)

    with EdgarClient(settings) as client:
        companies = ingest_universe(client, store)

    typer.echo(f"landed {len(companies)} companies")


@app.command()
def structured(
    tickers: Annotated[
        list[str] | None, typer.Argument(help="Tickers or CIKs; omit for the full universe")
    ] = None,
    limit: Annotated[int | None, typer.Option(help="Cap the number of companies")] = None,
) -> None:
    """Land XBRL facts and filing metadata. The broad layer."""
    settings = get_settings()
    ciks = _resolve(list(tickers)) if tickers else None
    report = ingest_structured(ciks, settings, limit=limit)

    typer.echo(report.summary())
    for error in report.errors[:20]:
        typer.echo(f"  error: {error}", err=True)


@app.command()
def text(
    tickers: Annotated[
        list[str] | None, typer.Argument(help="Tickers; omit for FINLENS_TEXT_UNIVERSE")
    ] = None,
    years: Annotated[int, typer.Option(help="Filings per company, newest first")] = 5,
) -> None:
    """Land 10-K documents. The narrow layer."""
    settings = get_settings()
    report = ingest_text(list(tickers) if tickers else None, settings, max_documents=years)

    typer.echo(report.summary())
    for error in report.errors[:20]:
        typer.echo(f"  error: {error}", err=True)


@app.command()
def frame(
    concept: Annotated[str, typer.Argument(help="XBRL concept, e.g. Assets")],
    year: Annotated[int, typer.Option(help="Calendar year")],
    quarter: Annotated[int | None, typer.Option(help="1-4; omit for annual")] = None,
    instant: Annotated[bool, typer.Option(help="Point-in-time concept (balances)")] = False,
    unit: str = "USD",
    taxonomy: str = "us-gaap",
) -> None:
    """Land one concept across every company for one period."""
    settings = get_settings()
    settings.ensure_dirs()
    store = get_store(settings)
    period = fr.frame_period(year, quarter, instant=instant)

    with EdgarClient(settings) as client:
        facts = fr.fetch_frame(client, concept, period=period, taxonomy=taxonomy, unit=unit)
        url = fr.frames_url(client, concept, period=period, taxonomy=taxonomy, unit=unit)

    if not facts:
        typer.echo(f"no frame for {concept} {period} ({unit}) - wrong instant/duration form?")
        raise typer.Exit(code=1)

    key = f"raw/frames/{taxonomy}_{concept}_{unit.replace('/', '-per-')}_{period}.json"
    land_json(store, key, [f.model_dump(mode="json") for f in facts], url=url)
    typer.echo(f"landed {len(facts)} company values for {concept} {period}")


@app.command()
def concepts() -> None:
    """Print the XBRL concepts the core marts are built from."""
    typer.echo(json.dumps(cf.CORE_CONCEPTS, indent=2))


@app.command()
def scope() -> None:
    """Show the configured universe for each layer."""
    settings = get_settings()
    typer.echo(f"structured: {settings.structured_universe_size} companies "
               f"from {settings.structured_year_min}")
    typer.echo(f"text:       {len(settings.text_universe)} companies "
               f"from {settings.text_year_min} - {', '.join(settings.text_universe)}")
    typer.echo(f"text items: {', '.join(settings.text_items)}")
    typer.echo(f"storage:    {settings.storage_backend}")


def _resolve(identifiers: list[str]) -> list[str]:
    """Turn a mixed list of tickers and CIKs into CIKs.

    Only hits the network if at least one argument is not already a CIK.
    """
    resolved: list[str] = []
    pending: list[str] = []
    for raw in identifiers:
        try:
            resolved.append(normalize_cik(raw))
        except ValueError:
            pending.append(raw.upper())

    if pending:
        with EdgarClient() as client:
            index = tk.build_ticker_index(tk.fetch_company_tickers(client))
        for ticker in pending:
            match = index.get(ticker)
            if match is None:
                raise typer.BadParameter(f"unknown ticker {ticker!r}")
            resolved.append(match.cik)
    return resolved


if __name__ == "__main__":
    app()
