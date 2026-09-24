"""Ticker <-> CIK resolution.

SEC publishes two overlapping files. ``company_tickers.json`` is the smaller,
canonical one; ``company_tickers_exchange.json`` adds the listing exchange,
which is the only reliable way to filter to listed companies. We read both and
join, because either alone leaves a gap users notice.
"""

from __future__ import annotations

from finlens.identifiers import normalize_cik
from finlens.ingest.client import EdgarClient
from finlens.ingest.models import Company
from finlens.logging import get_logger

log = get_logger(__name__)

TICKERS_PATH = "/files/company_tickers.json"
TICKERS_EXCHANGE_PATH = "/files/company_tickers_exchange.json"


def fetch_company_tickers(client: EdgarClient) -> list[Company]:
    """Return every company SEC maps to a ticker (~10k rows).

    ``company_tickers.json`` is a dict keyed by row index, not a list:
    ``{"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}``
    """
    payload = client.get_json(f"{client.www_url}{TICKERS_PATH}")
    if not isinstance(payload, dict):
        raise TypeError(f"expected an object from {TICKERS_PATH}, got {type(payload).__name__}")

    exchanges = _fetch_exchange_map(client)

    companies: list[Company] = []
    for row in payload.values():
        cik = normalize_cik(row["cik_str"])
        companies.append(
            Company(
                cik=cik,
                ticker=row.get("ticker") or None,
                name=row.get("title") or "",
                exchange=exchanges.get(cik),
            )
        )
    log.info("tickers.fetched", companies=len(companies), with_exchange=len(exchanges))
    return companies


def _fetch_exchange_map(client: EdgarClient) -> dict[str, str]:
    """CIK -> exchange, from the columnar ``{fields: [...], data: [...]}`` file.

    Treated as best-effort: the file is occasionally unavailable, and an absent
    exchange should not fail a whole ingest run.
    """
    payload = client.get_json(f"{client.www_url}{TICKERS_EXCHANGE_PATH}", allow_missing=True)
    if not isinstance(payload, dict) or "fields" not in payload:
        log.warning("tickers.exchange_unavailable")
        return {}

    fields: list[str] = payload["fields"]
    try:
        cik_idx, exch_idx = fields.index("cik"), fields.index("exchange")
    except ValueError:
        log.warning("tickers.exchange_schema_changed", fields=fields)
        return {}

    mapping: dict[str, str] = {}
    for row in payload.get("data", []):
        exchange = row[exch_idx]
        if exchange:
            mapping[normalize_cik(row[cik_idx])] = exchange
    return mapping


def build_ticker_index(companies: list[Company]) -> dict[str, Company]:
    """Uppercase ticker -> company.

    Later rows win on collision. Tickers get recycled after a delisting, and
    SEC orders the file by CIK, so "later" is not meaningfully "current" - the
    resolver in `finlens.agent` should treat an ambiguous ticker as ambiguous
    rather than trusting this map blindly.
    """
    return {c.ticker.upper(): c for c in companies if c.ticker}
