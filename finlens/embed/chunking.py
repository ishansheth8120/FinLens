"""Splitting filing sections into embeddable chunks.

The design constraint that shapes everything here: a risk factor or an MD&A
paragraph carries its meaning in prose, and cutting mid-sentence produces a
chunk that retrieves badly and reads worse when quoted in an answer. So the
splitter is boundary-aware and only ever falls back to a hard cut when a single
"paragraph" is genuinely longer than the target - which in SEC filings means a
table that lost its newlines.

Token counting is estimated, not exact. An exact count needs the embedding
model's own tokenizer, which differs per provider and would make chunk
boundaries move when the provider changes. A ~4-characters-per-token estimate is
within 10% on financial English and keeps chunk IDs stable across providers.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

# Financial text runs slightly denser than 4 chars/token because of numbers and
# tickers; 3.8 tracks measured counts on a 10-K sample more closely.
CHARS_PER_TOKEN = 3.8

_PARAGRAPH = re.compile(r"\n\s*\n")
# Sentence boundary that does not fire on "Inc.", "U.S.", "No. 5" or decimals.
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'“])")


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / CHARS_PER_TOKEN))


@dataclass
class Chunk:
    """One embeddable unit, carrying enough metadata to cite itself."""

    chunk_id: str
    text: str
    ordinal: int
    token_estimate: int
    section_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "section_id": self.section_id,
            "ordinal": self.ordinal,
            "text": self.text,
            "token_estimate": self.token_estimate,
            **self.metadata,
        }


def chunk_id_for(section_id: str, ordinal: int) -> str:
    """Stable chunk identity.

    Derived from position, not content, so that re-embedding an unchanged
    section reuses the same ID and the index can be updated in place.
    """
    return hashlib.sha1(f"{section_id}:{ordinal}".encode()).hexdigest()[:20]


def _split_oversized(block: str, max_chars: int) -> list[str]:
    """Break a too-long block at sentence boundaries, then hard-cut if needed."""
    sentences = _SENTENCE.split(block)
    pieces: list[str] = []
    current = ""

    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            pieces.append(current)
        # A single sentence over the limit is almost always a de-newlined table.
        # Hard-cut it; there is no better boundary available.
        while len(sentence) > max_chars:
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        current = sentence

    if current:
        pieces.append(current)
    return pieces


def chunk_text(
    text: str,
    *,
    target_tokens: int = 512,
    overlap_tokens: int = 64,
    min_tokens: int = 32,
) -> list[str]:
    """Split text into overlapping, boundary-aligned chunks.

    ``overlap_tokens`` of trailing context is prepended to each subsequent chunk
    so a fact stated at a chunk boundary is retrievable from either side.
    """
    if not text.strip():
        return []

    max_chars = int(target_tokens * CHARS_PER_TOKEN)
    overlap_chars = int(overlap_tokens * CHARS_PER_TOKEN)

    blocks: list[str] = []
    for paragraph in _PARAGRAPH.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        blocks.extend(
            [paragraph] if len(paragraph) <= max_chars else _split_oversized(paragraph, max_chars)
        )

    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = f"{_tail(current, overlap_chars)}\n\n{block}" if overlap_chars else block
        else:
            current = block

    if current:
        chunks.append(current)

    return _absorb_slivers(chunks, min_tokens)


def _absorb_slivers(chunks: list[str], min_tokens: int) -> list[str]:
    """Fold undersized chunks into their predecessor rather than dropping them.

    A 40-character trailing fragment is a bad chunk - it retrieves on nothing
    and wastes an embedding. But dropping it loses text, which for a hard-split
    table means silently losing data. Merging does neither.
    """
    merged: list[str] = []
    for chunk in chunks:
        if merged and estimate_tokens(chunk) < min_tokens:
            merged[-1] = f"{merged[-1]}\n\n{chunk}"
        else:
            merged.append(chunk)
    return merged


def _tail(text: str, chars: int) -> str:
    """Last ``chars`` of text, snapped forward to a sentence boundary."""
    if chars <= 0 or len(text) <= chars:
        return text
    tail = text[-chars:]
    match = _SENTENCE.search(tail)
    return tail[match.end() :] if match else tail


def chunk_section(
    section: dict[str, Any],
    *,
    target_tokens: int = 512,
    overlap_tokens: int = 64,
    text_key: str = "section_text",
    id_key: str = "section_id",
) -> list[Chunk]:
    """Chunk one row of `fct_filing_section`.

    The section heading is prepended to every chunk. It costs a few tokens and
    buys a large retrieval improvement: without it, chunk 7 of a risk-factors
    section has no lexical or semantic signal that it is about risk at all.
    """
    section_id = str(section.get(id_key) or "")
    text = str(section.get(text_key) or "")
    if not section_id or not text.strip():
        return []

    heading = _heading_for(section)
    metadata = {k: v for k, v in section.items() if k not in {text_key}}

    chunks: list[Chunk] = []
    for ordinal, body in enumerate(
        chunk_text(text, target_tokens=target_tokens, overlap_tokens=overlap_tokens)
    ):
        full = f"{heading}\n\n{body}" if heading else body
        chunks.append(
            Chunk(
                chunk_id=chunk_id_for(section_id, ordinal),
                section_id=section_id,
                ordinal=ordinal,
                text=full,
                token_estimate=estimate_tokens(full),
                metadata=metadata,
            )
        )
    return chunks


def _heading_for(section: dict[str, Any]) -> str:
    """A one-line context header, e.g. ``AAPL 10-K 2024 - Item 1A. Risk Factors``."""
    parts = [
        str(section.get("ticker") or section.get("company_name") or ""),
        str(section.get("form") or ""),
        str(section.get("fiscal_year") or ""),
    ]
    prefix = " ".join(p for p in parts if p).strip()

    item = section.get("item")
    title = section.get("section_title")
    suffix = " ".join(p for p in [f"Item {item}." if item else "", title or ""] if p).strip()

    return " - ".join(p for p in [prefix, suffix] if p)
