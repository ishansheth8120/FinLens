"""XBRL frames - one concept, one period, every company that reported it.

Endpoint: ``data.sec.gov/api/xbrl/frames/{taxonomy}/{concept}/{unit}/{period}.json``

The companyfacts API is company-major; frames is concept-major. For a
cross-sectional question ("who had the highest R&D spend in FY2023?") frames is
one request instead of ten thousand, so it is worth the separate code path.

Two gotchas encoded below: the unit segment replaces ``/`` with ``-per-``
(``USD/shares`` -> ``USD-per-shares``), and a *duration* period takes a trailing
``I``-less form while an *instant* period appends ``I`` (``CY2023Q1I``).
"""

from __future__ import annotations

from typing import Any

from finlens.ingest.client import EdgarClient
from finlens.ingest.models import Fact
from finlens.logging import get_logger

log = get_logger(__name__)


def frame_period(year: int, quarter: int | None = None, *, instant: bool = False) -> str:
    """Build a frame period string.

    >>> frame_period(2023)
    'CY2023'
    >>> frame_period(2023, 1)
    'CY2023Q1'
    >>> frame_period(2023, 1, instant=True)
    'CY2023Q1I'
    """
    period = f"CY{year}" if quarter is None else f"CY{year}Q{quarter}"
    return f"{period}I" if instant else period


def _unit_segment(unit: str) -> str:
    return unit.replace("/", "-per-")


def frames_url(
    client: EdgarClient,
    concept: str,
    *,
    period: str,
    taxonomy: str = "us-gaap",
    unit: str = "USD",
) -> str:
    return (
        f"{client.data_url}/api/xbrl/frames/{taxonomy}/{concept}/"
        f"{_unit_segment(unit)}/{period}.json"
    )


def fetch_frame(
    client: EdgarClient,
    concept: str,
    *,
    period: str,
    taxonomy: str = "us-gaap",
    unit: str = "USD",
) -> list[Fact]:
    """All companies' values for one concept in one period.

    Returns an empty list when the frame does not exist, which is normal:
    instant concepts have no duration frame and vice versa, and asking for the
    wrong one is a 404 rather than an empty result.
    """
    url = frames_url(client, concept, period=period, taxonomy=taxonomy, unit=unit)
    payload = client.get_json(url, allow_missing=True)
    if payload is None:
        log.debug("frames.absent", concept=concept, period=period, unit=unit)
        return []

    facts: list[Fact] = []
    for entry in payload.get("data", []):
        fact = _frame_entry_to_fact(entry, payload, taxonomy=taxonomy, concept=concept, unit=unit)
        if fact is not None:
            facts.append(fact)

    log.info("frames.fetched", concept=concept, period=period, companies=len(facts))
    return facts


def _frame_entry_to_fact(
    entry: dict[str, Any],
    payload: dict[str, Any],
    *,
    taxonomy: str,
    concept: str,
    unit: str,
) -> Fact | None:
    end = entry.get("end") or payload.get("endDate")
    if not end:
        return None
    try:
        return Fact(
            cik=entry["cik"],
            taxonomy=taxonomy,
            concept=concept,
            label=payload.get("label"),
            description=payload.get("description"),
            unit=unit,
            value=entry.get("val"),
            start_date=entry.get("start") or payload.get("startDate"),
            end_date=end,
            accession_number=entry.get("accn"),
            frame=payload.get("ccp") or payload.get("frame"),
        )
    except (KeyError, ValueError, TypeError) as exc:
        log.warning("frames.bad_entry", concept=concept, error=str(exc))
        return None
