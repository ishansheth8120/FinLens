"""Building the vector index from the warehouse.

Reads `fct_filing_section` out of the DuckDB warehouse, chunks it, embeds the
chunks and writes them to the index. Runs in bounded memory by streaming
sections in batches - a full corpus does not fit in RAM, and the failure mode
if it nearly does is an OOM three hours in.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from finlens.config import Settings, get_settings
from finlens.embed.chunking import chunk_section
from finlens.embed.providers import EmbeddingProvider, get_provider
from finlens.embed.store import VectorStore
from finlens.logging import get_logger

log = get_logger(__name__)

SECTION_QUERY = """
    SELECT
        section_id, cik, ticker, company_name, accession_number,
        form, filing_date, fiscal_year, item, section_title,
        citation_label, section_text
    FROM main_marts.fct_filing_section
    WHERE {predicate}
    ORDER BY section_id
    LIMIT ? OFFSET ?
"""


@dataclass
class IndexReport:
    sections: int = 0
    chunks: int = 0
    embedded: int = 0
    failed_batches: int = 0

    def summary(self) -> str:
        return (
            f"{self.sections} sections -> {self.chunks} chunks, "
            f"{self.embedded} embedded, {self.failed_batches} failed batches"
        )


def iter_sections(
    settings: Settings,
    *,
    forms: list[str] | None = None,
    fiscal_year_min: int | None = None,
    batch_size: int = 500,
    limit: int | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """Stream section rows out of the warehouse in batches."""
    import duckdb

    predicates = ["TRUE"]
    params: list[Any] = []
    if forms:
        predicates.append(f"form IN ({', '.join('?' for _ in forms)})")
        params.extend(forms)
    if fiscal_year_min is not None:
        predicates.append("fiscal_year >= ?")
        params.append(fiscal_year_min)

    query = SECTION_QUERY.format(predicate=" AND ".join(predicates))

    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    try:
        offset = 0
        yielded = 0
        while True:
            size = batch_size if limit is None else min(batch_size, limit - yielded)
            if size <= 0:
                return
            cursor = con.execute(query, [*params, size, offset])
            columns = [d[0] for d in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            if not rows:
                return
            yield rows
            offset += len(rows)
            yielded += len(rows)
    finally:
        con.close()


def build_index(
    settings: Settings | None = None,
    *,
    provider: EmbeddingProvider | None = None,
    forms: list[str] | None = None,
    fiscal_year_min: int | None = None,
    limit: int | None = None,
    rebuild: bool = False,
) -> IndexReport:
    """Chunk, embed and index the narrative corpus."""
    settings = settings or get_settings()
    provider = provider or get_provider(settings)
    report = IndexReport()

    if not provider.is_semantic:
        log.warning(
            "index.non_semantic_provider",
            provider=provider.name,
            detail="index will be built but retrieval quality is not meaningful",
        )

    store = VectorStore(dim=provider.dim, settings=settings)
    store.create(drop_existing=rebuild)

    try:
        for batch in iter_sections(
            settings, forms=forms, fiscal_year_min=fiscal_year_min, limit=limit
        ):
            report.sections += len(batch)
            chunks = [
                chunk
                for section in batch
                for chunk in chunk_section(
                    section,
                    target_tokens=settings.chunk_target_tokens,
                    overlap_tokens=settings.chunk_overlap_tokens,
                )
            ]
            report.chunks += len(chunks)
            if not chunks:
                continue

            for start in range(0, len(chunks), settings.embedding_batch_size):
                window = chunks[start : start + settings.embedding_batch_size]
                try:
                    vectors = provider.embed([c.text for c in window], input_type="document")
                except Exception as exc:  # noqa: BLE001 - a provider blip must not lose the run
                    report.failed_batches += 1
                    log.error("index.embed_failed", error=str(exc), batch_size=len(window))
                    continue

                if len(vectors) != len(window):
                    # A provider that silently returns a short batch would
                    # misalign every vector after the gap.
                    report.failed_batches += 1
                    log.error(
                        "index.batch_length_mismatch",
                        expected=len(window),
                        got=len(vectors),
                    )
                    continue

                rows = []
                for chunk, vector in zip(window, vectors):
                    metadata = chunk.metadata
                    rows.append(
                        {
                            "chunk_id": chunk.chunk_id,
                            "section_id": chunk.section_id,
                            "cik": metadata.get("cik"),
                            "ticker": metadata.get("ticker"),
                            "company_name": metadata.get("company_name"),
                            "accession_number": metadata.get("accession_number"),
                            "form": metadata.get("form"),
                            "filing_date": metadata.get("filing_date"),
                            "fiscal_year": metadata.get("fiscal_year"),
                            "item": metadata.get("item"),
                            "section_title": metadata.get("section_title"),
                            "citation_label": metadata.get("citation_label"),
                            "ordinal": chunk.ordinal,
                            "token_estimate": chunk.token_estimate,
                            "text": chunk.text,
                            "embedding": vector,
                        }
                    )
                report.embedded += store.upsert(rows)

            log.info("index.progress", **report.__dict__)

        # BM25 is rebuilt at the end rather than incrementally: DuckDB's FTS
        # index is a materialised structure, so updating it per batch would be
        # quadratic.
        store.create_fts_index()
    finally:
        store.close()

    log.info("index.complete", summary=report.summary())
    return report
