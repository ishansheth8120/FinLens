"""XBRL company facts - every number a company has ever tagged.

Endpoint: ``data.sec.gov/api/xbrl/companyfacts/CIK##########.json``

The payload nests four levels deep::

    facts -> taxonomy ("us-gaap") -> concept ("Assets") -> units ("USD") -> [fact, ...]

Flattening it is most of this module. The rest is the two facts about the data
that make or break every downstream number:

1. **Restatements.** A concept/period pair appears once per filing that reported
   it. Ten years of 10-Ks means the same FY2019 revenue shows up repeatedly,
   sometimes with different values. We keep them all and let the warehouse pick.
2. **Instants vs durations.** A fact with only ``end`` is a balance at a point
   in time; one with ``start`` and ``end`` covers a period. Summing the former
   across quarters produces nonsense.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from finlens.identifiers import normalize_cik
from finlens.ingest.client import EdgarClient
from finlens.ingest.models import Fact
from finlens.logging import get_logger

log = get_logger(__name__)

# Concepts the warehouse's core financial marts are built on. Ingest keeps
# everything; this list is for callers that want a cheap targeted pull.
CORE_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_income": ("OperatingIncomeLoss",),
    "gross_profit": ("GrossProfit",),
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "stockholders_equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "rd_expense": ("ResearchAndDevelopmentExpense",),
    "shares_diluted": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "eps_diluted": ("EarningsPerShareDiluted",),
}


def companyfacts_url(client: EdgarClient, cik: str | int) -> str:
    return f"{client.data_url}/api/xbrl/companyfacts/CIK{normalize_cik(cik)}.json"


def fetch_companyfacts(client: EdgarClient, cik: str | int) -> dict[str, Any] | None:
    """Raw companyfacts payload.

    ``None`` means the company has never filed XBRL - true for many small and
    foreign private issuers, and for anything filed before ~2009.
    """
    return client.get_json(companyfacts_url(client, cik), allow_missing=True)


def iter_facts(
    payload: dict[str, Any],
    *,
    taxonomies: tuple[str, ...] | None = None,
    concepts: set[str] | None = None,
) -> Iterator[Fact]:
    """Flatten a companyfacts payload into `Fact` rows.

    A generator because a large filer's payload holds >100k facts and callers
    typically write straight to Parquet.
    """
    cik = normalize_cik(payload.get("cik", 0))

    for taxonomy, taxonomy_facts in (payload.get("facts") or {}).items():
        if taxonomies and taxonomy not in taxonomies:
            continue
        for concept, concept_body in (taxonomy_facts or {}).items():
            if concepts and concept not in concepts:
                continue
            label = concept_body.get("label")
            description = concept_body.get("description")
            for unit, entries in (concept_body.get("units") or {}).items():
                for entry in entries:
                    fact = _build_fact(
                        cik=cik,
                        taxonomy=taxonomy,
                        concept=concept,
                        label=label,
                        description=description,
                        unit=unit,
                        entry=entry,
                    )
                    if fact is not None:
                        yield fact


def _build_fact(
    *,
    cik: str,
    taxonomy: str,
    concept: str,
    label: str | None,
    description: str | None,
    unit: str,
    entry: dict[str, Any],
) -> Fact | None:
    # `end` is the only field EDGAR guarantees; without it the fact cannot be
    # placed on a timeline and is useless to us.
    if not entry.get("end"):
        return None
    try:
        return Fact(
            cik=cik,
            taxonomy=taxonomy,
            concept=concept,
            label=label,
            description=description,
            unit=unit,
            value=entry.get("val"),
            start_date=entry.get("start"),
            end_date=entry["end"],
            fiscal_year=entry.get("fy"),
            fiscal_period=entry.get("fp"),
            form=entry.get("form"),
            filed_date=entry.get("filed"),
            accession_number=entry.get("accn"),
            frame=entry.get("frame"),
        )
    except (ValueError, TypeError) as exc:
        log.warning("companyfacts.bad_fact", cik=cik, concept=concept, unit=unit, error=str(exc))
        return None


def core_concept_names() -> set[str]:
    """Flattened set of every concept in `CORE_CONCEPTS`."""
    return {c for group in CORE_CONCEPTS.values() for c in group}
