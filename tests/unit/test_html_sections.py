from __future__ import annotations

from finlens.spark.html_sections import (
    html_to_text,
    parse_filing,
    section_id,
    split_sections,
)


def test_script_and_style_content_is_dropped(filing_html):
    text = html_to_text(filing_html)
    assert "var tracking" not in text
    assert "color: red" not in text


def test_table_cells_are_separated(filing_html):
    text = html_to_text(filing_html)
    # Without cell separators these concatenate into "2023383,285", which
    # embeds as garbage.
    assert "2023383,285" not in text
    assert "383,285" in text


def test_entities_are_unescaped():
    assert html_to_text("<p>AT&amp;T &lt;tag&gt;</p>").strip() == "AT&T <tag>"


def test_malformed_html_still_yields_text():
    text = html_to_text("<p>unclosed <div>nested <span>text")
    assert "unclosed" in text and "text" in text


def test_table_of_contents_is_not_mistaken_for_sections(filing_html):
    sections = parse_filing(filing_html, form="10-K")
    items = [s.item for s in sections]

    # The TOC lists six items; only three have real bodies. If the TOC were
    # picked up, Item 1's body would be the table of contents itself.
    assert items == ["1", "1A", "7"]

    business = next(s for s in sections if s.item == "1")
    assert "designs and markets smartphones" in business.text
    assert "TABLE OF CONTENTS" not in business.text


def test_sections_carry_titles_and_counts(filing_html):
    sections = parse_filing(filing_html, form="10-K")
    risk = next(s for s in sections if s.item == "1A")
    assert "Risk Factors" in (risk.title or "")
    assert risk.word_count > 50
    assert risk.char_count == len(risk.text)


def test_document_with_no_items_becomes_one_section():
    text = "An 8-K body with no item headings at all. " * 20
    sections = split_sections(text, form="8-K")
    assert len(sections) == 1
    assert sections[0].item is None


def test_empty_document_yields_no_sections():
    assert split_sections("   ", form="10-K") == []


def test_short_sections_fold_into_the_previous_one():
    text = (
        "Item 1. Business\n" + ("Substantial body text. " * 40) + "\n"
        "Item 1B. Unresolved Staff Comments\nNone.\n"
        "Item 2. Properties\n" + ("More substantial body text. " * 40)
    )
    sections = split_sections(text, form="10-K", min_section_chars=200)
    items = [s.item for s in sections]

    assert "1B" not in items
    business = next(s for s in sections if s.item == "1")
    assert "Unresolved Staff Comments" in business.text


def test_section_id_is_stable_and_position_based():
    # Stable across re-parses so improving the parser does not orphan embeddings.
    assert section_id("0000320193", "0000320193-24-000123", 3) == section_id(
        "0000320193", "0000320193-24-000123", 3
    )
    assert section_id("0000320193", "0000320193-24-000123", 3) != section_id(
        "0000320193", "0000320193-24-000123", 4
    )


def test_tenq_uses_its_own_item_titles():
    text = (
        "Item 1. Financial Statements\n" + ("Body. " * 60) + "\n"
        "Item 2. Management's Discussion and Analysis\n" + ("Body. " * 60)
    )
    sections = split_sections(text, form="10-Q")
    assert [s.item for s in sections] == ["1", "2"]
