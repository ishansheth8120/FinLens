from __future__ import annotations

from finlens.embed.chunking import (
    chunk_id_for,
    chunk_section,
    chunk_text,
    estimate_tokens,
)


def test_short_text_is_one_chunk():
    assert len(chunk_text("A single short paragraph.", target_tokens=512)) == 1


def test_empty_text_yields_nothing():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_long_text_splits_into_multiple_chunks():
    text = "\n\n".join(["Paragraph number %d with some content." % i for i in range(300)])
    chunks = chunk_text(text, target_tokens=128, overlap_tokens=16)
    assert len(chunks) > 1


def test_chunks_respect_the_target_size():
    text = "\n\n".join(["Paragraph %d. %s" % (i, "word " * 30) for i in range(50)])
    chunks = chunk_text(text, target_tokens=128, overlap_tokens=0)
    # 128 tokens * 3.8 chars/token, with slack for the boundary-aligned join.
    assert all(len(c) <= int(128 * 3.8) * 1.5 for c in chunks)


def test_overlap_carries_context_between_chunks():
    text = "\n\n".join(["Distinct paragraph %d content here." % i for i in range(120)])
    with_overlap = chunk_text(text, target_tokens=64, overlap_tokens=24)
    without_overlap = chunk_text(text, target_tokens=64, overlap_tokens=0)
    # Overlap duplicates trailing context, so total characters must exceed the
    # non-overlapping split.
    assert sum(len(c) for c in with_overlap) > sum(len(c) for c in without_overlap)


def test_a_single_oversized_paragraph_is_hard_split():
    # A de-newlined table: one "paragraph" far over the limit and no sentence
    # boundaries to cut on.
    monolith = "x" * 10000
    chunks = chunk_text(monolith, target_tokens=64, overlap_tokens=0)
    assert len(chunks) > 1
    assert "".join(chunks).count("x") == 10000


def test_estimate_tokens_is_never_zero_for_content():
    assert estimate_tokens("a") >= 1
    assert estimate_tokens("word " * 100) > 50


def test_chunk_section_prepends_a_context_heading():
    section = {
        "section_id": "abc123",
        "section_text": "The Company depends on single-source suppliers. " * 40,
        "ticker": "AAPL",
        "form": "10-K",
        "fiscal_year": 2024,
        "item": "1A",
        "section_title": "Risk Factors",
    }
    chunks = chunk_section(section, target_tokens=64, overlap_tokens=8)

    assert chunks
    # Every chunk, not just the first: chunk 7 of a risk section otherwise has
    # no signal that it is about risk.
    assert all(c.text.startswith("AAPL 10-K 2024 - Item 1A. Risk Factors") for c in chunks)


def test_chunk_section_carries_metadata_and_ids():
    section = {
        "section_id": "abc123",
        "section_text": "Body text. " * 100,
        "cik": "0000320193",
        "accession_number": "0000320193-24-000123",
    }
    chunks = chunk_section(section, target_tokens=64)

    assert all(c.section_id == "abc123" for c in chunks)
    assert chunks[0].chunk_id == chunk_id_for("abc123", 0)
    assert chunks[0].metadata["cik"] == "0000320193"
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_chunk_section_skips_rows_with_no_text():
    assert chunk_section({"section_id": "x", "section_text": ""}) == []
    assert chunk_section({"section_id": "", "section_text": "content"}) == []


def test_chunk_ids_are_stable_across_runs():
    assert chunk_id_for("sec1", 2) == chunk_id_for("sec1", 2)
    assert chunk_id_for("sec1", 2) != chunk_id_for("sec2", 2)
