from __future__ import annotations

import pytest

from finlens.embed.providers import HashEmbeddingProvider
from finlens.embed.store import Filters, VectorStore

DIM = 64


@pytest.fixture
def provider():
    return HashEmbeddingProvider(dim=DIM)


@pytest.fixture
def store(settings, provider):
    store = VectorStore(dim=DIM, settings=settings)
    store.create(drop_existing=True)

    documents = [
        ("c1", "0000320193", "AAPL", "10-K", 2023, "1A", "Supply chain disruption risk in Asia."),
        ("c2", "0000320193", "AAPL", "10-K", 2023, "7", "Gross margin improved on product mix."),
        ("c3", "0000789019", "MSFT", "10-K", 2023, "1A", "Cloud infrastructure outage risk."),
        ("c4", "0000789019", "MSFT", "10-Q", 2024, "1A", "Currency exchange rate exposure."),
    ]
    rows = []
    for chunk_id, cik, ticker, form, year, item, text in documents:
        rows.append(
            {
                "chunk_id": chunk_id,
                "section_id": f"s-{chunk_id}",
                "cik": cik,
                "ticker": ticker,
                "company_name": ticker,
                "accession_number": f"acc-{chunk_id}",
                "form": form,
                "fiscal_year": year,
                "item": item,
                "section_title": "Section",
                "citation_label": f"{ticker} {form} {year}, Item {item}",
                "ordinal": 0,
                "token_estimate": 10,
                "text": text,
                "embedding": provider.embed_one(text),
            }
        )
    store.upsert(rows)
    store.create_fts_index()
    yield store
    store.close()


def test_upsert_and_count(store):
    assert store.count() == 4


def test_upsert_is_idempotent(store, provider):
    store.upsert(
        [
            {
                "chunk_id": "c1",
                "text": "Replaced text.",
                "embedding": provider.embed_one("Replaced text."),
            }
        ]
    )
    assert store.count() == 4


def test_vector_search_returns_ranked_hits(store, provider):
    hits = store.vector_search(provider.embed_one("supply chain disruption"), top_k=4)
    assert hits
    assert hits[0].score >= hits[-1].score


def test_ticker_filter_excludes_other_companies(store, provider):
    hits = store.vector_search(
        provider.embed_one("risk"), top_k=10, filters=Filters(tickers=["AAPL"])
    )
    assert hits
    assert {h.metadata["ticker"] for h in hits} == {"AAPL"}


def test_item_and_form_filters_compose(store, provider):
    hits = store.vector_search(
        provider.embed_one("risk"),
        top_k=10,
        filters=Filters(items=["1A"], forms=["10-K"]),
    )
    assert {h.metadata["item"] for h in hits} == {"1A"}
    assert {h.metadata["form"] for h in hits} == {"10-K"}


def test_fiscal_year_range_filter(store, provider):
    hits = store.vector_search(
        provider.embed_one("risk"), top_k=10, filters=Filters(fiscal_year_min=2024)
    )
    assert all(h.metadata["fiscal_year"] >= 2024 for h in hits)


def test_a_filter_matching_nothing_returns_nothing(store, provider):
    hits = store.vector_search(
        provider.embed_one("risk"), top_k=10, filters=Filters(tickers=["NOPE"])
    )
    assert hits == []


def test_keyword_search_finds_exact_terms(store):
    hits = store.keyword_search("outage", top_k=5)
    assert any(h.chunk_id == "c3" for h in hits)


def test_hybrid_search_fuses_both_arms(store, provider):
    hits = store.hybrid_search("cloud outage", provider.embed_one("cloud outage"), top_k=4)
    assert hits
    assert any(h.chunk_id == "c3" for h in hits)
    # RRF scores, not cosine similarities.
    assert all(0 < h.score < 1 for h in hits)


def test_citation_label_survives_the_round_trip(store, provider):
    hits = store.vector_search(provider.embed_one("supply chain"), top_k=1)
    assert hits[0].citation.startswith("AAPL 10-K")


def test_filters_render_parameterised_sql():
    where, params = Filters(tickers=["AAPL"], fiscal_year_min=2020).to_sql()
    assert "?" in where
    assert params == ["AAPL", 2020]
    # No user-supplied value is ever interpolated into the SQL text.
    assert "AAPL" not in where


def test_filters_can_be_prefixed_for_joins():
    where, _ = Filters(tickers=["AAPL"]).to_sql(prefix="t.")
    assert where.startswith("t.ticker IN")


def test_empty_filters_are_a_no_op():
    where, params = Filters().to_sql()
    assert where == "TRUE"
    assert params == []
