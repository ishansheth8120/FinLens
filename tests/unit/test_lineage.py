from __future__ import annotations

from finlens.agent.types import Citation
from finlens.governance.lineage import filing_url, trace, trace_citation, trace_table


def test_filing_url_resolves_to_sec_gov():
    url = filing_url("0000320193", "0000320193-24-000123", "aapl-20240928.htm")
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019324000123/aapl-20240928.htm"
    )


def test_filing_url_without_a_document_points_at_the_directory():
    assert filing_url(320193, "0000320193-24-000123").endswith("000032019324000123/")


def test_a_mart_traces_back_to_the_raw_zone(settings):
    trail = trace_table("marts.fct_company_annual", settings)
    layers = [n.layer for n in trail.nodes]

    # The full chain has to be present, or the lineage claim is decorative.
    assert "dbt model" in layers
    assert "dbt staging" in layers
    assert "lake (silver)" in layers
    assert "lake (raw)" in layers
    assert layers[-1] == "source"


def test_the_chain_reaches_the_right_raw_dataset(settings):
    trail = trace_table("fct_company_annual", settings)
    names = [n.name for n in trail.nodes]
    assert "raw/companyfacts" in names


def test_a_narrative_mart_traces_to_documents_not_facts(settings):
    trail = trace_table("fct_filing_section", settings)
    names = [n.name for n in trail.nodes]
    assert "raw/documents" in names


def test_a_citation_traces_to_a_filing_url(settings):
    citation = Citation(
        label="AAPL 10-K 2024, Item 1A",
        source_type="filing",
        chunk_id="abc123",
        section_id="sec456",
        accession_number="0000320193-24-000123",
    )
    trail = trace_citation({**citation.model_dump(), "cik": "0000320193"}, settings)

    assert trail.accession_number == "0000320193-24-000123"
    assert trail.source_url is not None
    assert trail.source_url.startswith("https://www.sec.gov/Archives/")
    assert any(n.layer == "vector index" for n in trail.nodes)


def test_a_citation_without_a_cik_still_traces_as_far_as_it_can(settings):
    trail = trace_citation({"label": "x", "chunk_id": "c1"}, settings)
    assert trail.nodes
    assert trail.source_url is None


def test_trace_covers_tables_and_citations_together(settings):
    trails = trace(
        tables=["marts.fct_company_annual"],
        citations=[{"label": "AAPL 10-K", "chunk_id": "c1", "cik": "0000320193",
                    "accession_number": "0000320193-24-000123"}],
        settings=settings,
    )
    assert len(trails) == 2


def test_render_is_readable(settings):
    rendered = trace_table("marts.dim_company", settings).render()
    assert "->" in rendered
    assert "SEC EDGAR" in rendered


def test_to_dict_is_serialisable(settings):
    payload = trace_table("marts.dim_company", settings).to_dict()
    assert "chain" in payload
    assert all({"layer", "name", "detail"} <= set(hop) for hop in payload["chain"])
