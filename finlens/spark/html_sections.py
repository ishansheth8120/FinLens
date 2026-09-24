"""Turning filing HTML into item-level sections.

Deliberately dependency-free (stdlib ``html.parser`` only) so it can be unit
tested without a JVM or a C extension, and so the Spark executors need nothing
installed beyond the project itself.

Two problems make this harder than "strip the tags":

**The table of contents.** Every 10-K opens with a TOC listing "Item 1A. Risk
Factors" and friends. A naive regex splits the document at the TOC entry, so
"Item 1A" ends up containing the table of contents rather than the risk
factors. `_drop_toc_cluster` finds the dense run of item headers near the top
and discards it.

**Layout tables.** SEC filings use tables for visual layout, not just data.
Concatenating cell text without separators glues unrelated numbers into strings
like ``12,4501,203``, which then embed as garbage. Cells are joined with a tab
and rows with a newline.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser

# Tags whose content is markup machinery, never prose.
_DROP_CONTENT = frozenset({"script", "style", "head", "title", "meta", "link"})
# Tags that imply a line break when they close.
_BLOCK = frozenset(
    {
        "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "table", "thead", "tbody", "blockquote", "hr",
    }
)  # fmt: skip
_CELL = frozenset({"td", "th"})

_WS_RUN = re.compile(r"[ \t\xa0]+")
_BLANK_RUN = re.compile(r"\n{3,}")

# "Item 7A.", "ITEM 1A -", "Item 9B" - the separator and case both vary, and
# many filings interpose non-breaking spaces.
_ITEM_HEADER = re.compile(
    r"(?im)^[ \t]*item[\s\xa0]+(\d{1,2}[A-C]?)[\s\xa0]*[.:–—-]?[ \t]*(.{0,80})$"
)

# Canonical 10-K item titles, used to label sections and to sanity-check that a
# match is a real header rather than a cross-reference in body text.
TENK_ITEMS: dict[str, str] = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity",
    "6": "Selected Financial Data",
    "7": "Management's Discussion and Analysis",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership of Certain Beneficial Owners",
    "13": "Certain Relationships and Related Transactions",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibits and Financial Statement Schedules",
}

TENQ_ITEMS: dict[str, str] = {
    "1": "Financial Statements",
    "2": "Management's Discussion and Analysis",
    "3": "Quantitative and Qualitative Disclosures About Market Risk",
    "4": "Controls and Procedures",
}


@dataclass(frozen=True)
class Section:
    item: str | None
    title: str | None
    ordinal: int
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


class _TextExtractor(HTMLParser):
    """Collect visible text, preserving enough structure to stay readable."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._suppress = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _DROP_CONTENT:
            self._suppress += 1
        elif tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_CONTENT:
            self._suppress = max(0, self._suppress - 1)
        elif tag in _CELL:
            self.parts.append("\t")
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._suppress:
            self.parts.append(data)


def html_to_text(html: str | bytes) -> str:
    """Extract normalised plain text from filing HTML."""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")

    parser = _TextExtractor()
    # Malformed markup is the norm in older filings; never let it abort a job.
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - partial text beats no text
        pass

    text = "".join(parser.parts)
    text = text.replace("\xa0", " ")
    lines = [_WS_RUN.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()


def _find_item_headers(text: str) -> list[tuple[int, str, str]]:
    """(position, item_key, trailing_text) for every plausible item header."""
    found: list[tuple[int, str, str]] = []
    for match in _ITEM_HEADER.finditer(text):
        item = match.group(1).upper()
        trailing = (match.group(2) or "").strip(" .:-–—")
        found.append((match.start(), item, trailing))
    return found


def _drop_toc_cluster(
    headers: list[tuple[int, str, str]],
    *,
    max_gap: int = 500,
    min_items: int = 5,
) -> list[tuple[int, str, str]]:
    """Remove the dense run of headers that is the table of contents.

    Detection is by *adjacency*, not by absolute position or window size. TOC
    entries are consecutive lines a few dozen characters apart; real item
    headers are separated by the section body between them, which is thousands
    of characters. So: group headers into runs where each is within ``max_gap``
    of the next, and drop any run covering ``min_items`` or more distinct items.

    An absolute character window fails on short documents, where the entire
    filing fits inside one window and every header looks like a TOC entry.

    A run of two or three adjacent headers is left alone - that is a genuinely
    empty section ("Item 1B. None."), not a contents table.
    """
    if len(headers) < min_items:
        return headers

    # A header is "bare" when almost no text follows it before the next header -
    # i.e. it labels nothing. The measure is the gap *after* each header, not
    # between pairs: the last TOC entry is immediately followed by the first
    # real heading, so a pairwise grouping sweeps that real heading into the
    # contents run and loses Item 1 from the output.
    bare = [
        (headers[i + 1][0] - headers[i][0]) <= max_gap if i + 1 < len(headers) else False
        for i in range(len(headers))
    ]

    runs: list[list[int]] = []
    for i, is_bare in enumerate(bare):
        if not is_bare:
            continue
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])

    drop: set[int] = set()
    for run in runs:
        if len({headers[i][1] for i in run}) >= min_items:
            drop.update(run)

    remaining = [h for i, h in enumerate(headers) if i not in drop]
    # If everything looked like a TOC, the document probably is mostly one.
    return remaining or headers


def _dedupe_keep_first(headers: list[tuple[int, str, str]]) -> list[tuple[int, str, str]]:
    seen: set[str] = set()
    kept: list[tuple[int, str, str]] = []
    for pos, item, trailing in headers:
        if item not in seen:
            seen.add(item)
            kept.append((pos, item, trailing))
    return kept


def split_sections(
    text: str,
    *,
    form: str = "10-K",
    min_section_chars: int = 200,
) -> list[Section]:
    """Split filing text into item sections.

    Falls back to a single ``None``-item section when no headers survive
    filtering - true for 8-Ks and for the minority of filings whose items are
    rendered as images or deeply nested tables. A whole-document section still
    chunks and embeds usefully; it just cannot be filtered by item.
    """
    titles = TENQ_ITEMS if form.startswith("10-Q") else TENK_ITEMS

    headers = _dedupe_keep_first(_drop_toc_cluster(_find_item_headers(text)))
    headers = [h for h in headers if h[1] in titles]
    headers.sort(key=lambda h: h[0])

    if not headers:
        stripped = text.strip()
        return [Section(item=None, title=None, ordinal=0, text=stripped)] if stripped else []

    sections: list[Section] = []
    for ordinal, (pos, item, trailing) in enumerate(headers):
        end = headers[ordinal + 1][0] if ordinal + 1 < len(headers) else len(text)
        body = text[pos:end].strip()
        if len(body) < min_section_chars and sections:
            # Too short to stand alone - almost always a cross-reference like
            # "Item 1B. None." Fold it into the previous section rather than
            # emitting a chunk that is pure boilerplate.
            previous = sections[-1]
            sections[-1] = Section(
                item=previous.item,
                title=previous.title,
                ordinal=previous.ordinal,
                text=f"{previous.text}\n\n{body}",
            )
            continue
        sections.append(
            Section(
                item=item,
                title=trailing if len(trailing) > 3 else titles.get(item),
                ordinal=len(sections),
                text=body,
            )
        )
    return sections


def section_id(cik: str, accession: str, ordinal: int) -> str:
    """Stable identifier so re-parsing the same filing keeps the same IDs.

    Content-independent on purpose: the vector index joins on it, and an ID that
    changed when the parser improved would orphan every embedding.
    """
    raw = f"{cik}:{accession}:{ordinal}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def parse_filing(
    html: str | bytes,
    *,
    form: str = "10-K",
    min_section_chars: int = 200,
) -> list[Section]:
    """HTML in, item sections out."""
    return split_sections(html_to_text(html), form=form, min_section_chars=min_section_chars)
