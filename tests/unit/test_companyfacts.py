from __future__ import annotations

from datetime import date

from finlens.ingest.companyfacts import CORE_CONCEPTS, core_concept_names, iter_facts


def test_flattens_the_nested_payload(companyfacts_payload):
    facts = list(iter_facts(companyfacts_payload))
    # 2 Revenues + 1 valid Assets. The Assets entry with no `end` is dropped.
    assert len(facts) == 3
    assert {f.concept for f in facts} == {"Revenues", "Assets"}


def test_drops_facts_with_no_end_date(companyfacts_payload):
    # A fact with no end cannot be placed on a timeline; defaulting it would
    # silently invent a period.
    assets = [f for f in iter_facts(companyfacts_payload) if f.concept == "Assets"]
    assert len(assets) == 1
    assert assets[0].end_date == date(2023, 9, 30)


def test_keeps_both_restatement_vintages(companyfacts_payload):
    revenues = [f for f in iter_facts(companyfacts_payload) if f.concept == "Revenues"]
    assert len(revenues) == 2
    assert {f.value for f in revenues} == {383285000000.0, 383290000000.0}
    # Distinguishable by the filing they came from - the warehouse ranks on this.
    assert {f.accession_number for f in revenues} == {
        "0000320193-23-000106",
        "0000320193-24-000123",
    }


def test_duration_and_instant_are_distinguishable(companyfacts_payload):
    facts = {f.concept: f for f in iter_facts(companyfacts_payload) if f.concept == "Assets"}
    revenues = [f for f in iter_facts(companyfacts_payload) if f.concept == "Revenues"]

    assert facts["Assets"].is_duration is False
    assert revenues[0].is_duration is True


def test_concept_filter(companyfacts_payload):
    facts = list(iter_facts(companyfacts_payload, concepts={"Assets"}))
    assert {f.concept for f in facts} == {"Assets"}


def test_taxonomy_filter_excludes_everything_unmatched(companyfacts_payload):
    assert list(iter_facts(companyfacts_payload, taxonomies=("ifrs-full",))) == []


def test_cik_is_normalised_from_the_payload(companyfacts_payload):
    facts = list(iter_facts(companyfacts_payload))
    assert all(f.cik == "0000320193" for f in facts)


def test_core_concept_names_is_flat_and_deduplicated():
    names = core_concept_names()
    assert "NetIncomeLoss" in names
    assert len(names) == len({c for group in CORE_CONCEPTS.values() for c in group})
