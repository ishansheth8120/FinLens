"""Retrieval over filing text.

Three steps, each earning its place:

**Filtering.** The router's entities become metadata predicates. This is the
single largest quality lever in the whole RAG path — "Apple's supply chain risk"
searched across 10,000 companies returns Apple's competitors' risk factors,
which are near-identical in wording and completely wrong as an answer.

**Hybrid search.** Dense retrieval plus BM25, fused by reciprocal rank. Filings
are full of exact strings — tickers, item numbers, defined terms, dollar
amounts — that dense retrieval handles poorly and lexical search nails.

**Reranking.** Optional cross-encoder pass over the top candidates. Off by
default because it adds latency and a dependency; the hook is here because on
this corpus it is worth about as much as everything else combined, and the eval
harness can measure exactly that.
"""

from __future__ import annotations

import time

from finlens.agent.types import Citation, Entities, RetrievalResult
from finlens.config import Settings, get_settings
from finlens.embed.providers import EmbeddingProvider, get_provider
from finlens.embed.store import Filters, SearchHit, VectorStore
from finlens.logging import get_logger

log = get_logger(__name__)

# Chunks below this cosine similarity are noise even when they rank highly -
# which happens whenever the filters leave few candidates and everything left is
# irrelevant. Better to return three good chunks than eight padded with junk.
MIN_DENSE_SCORE = 0.15


def entities_to_filters(
    entities: Entities | None, permitted_ciks: list[str] | None = None
) -> Filters:
    """Translate the router's extraction into index predicates.

    Years become a *range* rather than an exact set: a question about 2023 is
    usually answered by the FY2023 10-K, which may be filed and labelled 2024,
    and an exact-match filter on a single year is the most common way to get
    zero results for a question the corpus can answer.

    ``permitted_ciks`` is the access scope and it *overrides* the question's own
    entity filter rather than merging with it. An empty list therefore matches
    nothing, which is the correct behaviour for a principal asking about a
    company they are not entitled to see.
    """
    entities = entities or Entities()
    years = entities.fiscal_years

    return Filters(
        # When a scope is supplied it wins outright. Falling back to the
        # question's tickers here would let an unentitled company back in
        # through the ticker predicate.
        ciks=permitted_ciks if permitted_ciks is not None else (entities.ciks or None),
        tickers=(
            None if permitted_ciks is not None else ([t.upper() for t in entities.tickers] or None)
        ),
        forms=entities.forms or None,
        items=entities.items or None,
        fiscal_year_min=min(years) if years else None,
        fiscal_year_max=max(years) + 1 if years else None,
    )


def _hit_to_citation(hit: SearchHit, index: int) -> Citation:
    metadata = hit.metadata
    return Citation(
        label=hit.citation,
        source_type="filing",
        chunk_id=hit.chunk_id,
        section_id=metadata.get("section_id"),
        accession_number=metadata.get("accession_number"),
        excerpt=hit.text[:500],
        score=hit.score,
    )


def _format_context(hit: SearchHit, index: int) -> str:
    """Render one hit for the synthesis prompt, numbered for citation."""
    return f"[{index}] {hit.citation}\n{hit.text}"


def retrieve(
    question: str,
    *,
    entities: Entities | None = None,
    settings: Settings | None = None,
    provider: EmbeddingProvider | None = None,
    store: VectorStore | None = None,
    top_k: int | None = None,
    top_n: int | None = None,
    widen_if_empty: bool = True,
    permitted_ciks: list[str] | None = None,
) -> RetrievalResult:
    """Retrieve and rank filing excerpts for a question, within scope."""
    settings = settings or get_settings()
    provider = provider or get_provider(settings)
    top_k = top_k or settings.retrieval_top_k
    top_n = top_n or settings.rerank_top_n

    owns_store = store is None
    if store is None:
        from finlens.embed.pgvector_store import get_vector_store

        store = get_vector_store(settings)
    started = time.perf_counter()

    try:
        query_vector = provider.embed_one(question, input_type="query")
        filters = entities_to_filters(entities, permitted_ciks)

        # A principal scoped to nothing must retrieve nothing. Short-circuiting
        # is clearer than relying on `IN ()` semantics, and it saves the query.
        if permitted_ciks is not None and not permitted_ciks:
            log.info("rag.empty_scope", detail="principal is entitled to no companies")
            return RetrievalResult(query=question)

        hits = store.hybrid_search(question, query_vector, top_k=top_k, filters=filters)

        # A filter that matches nothing is far more common than a corpus that
        # contains nothing relevant - usually a year range that is too tight, or
        # an item number the section parser did not detect. Widen, but never
        # past the access scope: the CIK filter is retained.
        if not hits and widen_if_empty and filters != Filters():
            log.info("rag.widening", detail="filtered search returned nothing")
            hits = store.hybrid_search(
                question,
                query_vector,
                top_k=top_k,
                filters=Filters(ciks=filters.ciks),
            )

        ranked = rerank(question, hits, top_n=top_n, provider=provider)
    finally:
        if owns_store:
            store.close()

    elapsed_ms = (time.perf_counter() - started) * 1000
    log.info("rag.retrieved", hits=len(ranked), elapsed_ms=round(elapsed_ms, 1))

    return RetrievalResult(
        query=question,
        citations=[_hit_to_citation(h, i) for i, h in enumerate(ranked, start=1)],
        contexts=[_format_context(h, i) for i, h in enumerate(ranked, start=1)],
        elapsed_ms=elapsed_ms,
    )


def rerank(
    question: str,
    hits: list[SearchHit],
    *,
    top_n: int = 8,
    provider: EmbeddingProvider | None = None,
) -> list[SearchHit]:
    """Reduce candidates to the final context set.

    Currently rank-preserving with light diversification: at most three chunks
    from any one filing, so a single verbose 10-K cannot crowd out the other
    companies in a comparison. That failure mode is common and this fixes most
    of it for no extra cost.

    The cross-encoder version belongs here. It is left unimplemented rather than
    stubbed with something that pretends to rerank, so the eval numbers describe
    what the system actually does.
    """
    if not hits:
        return []

    per_filing: dict[str, int] = {}
    selected: list[SearchHit] = []

    for hit in hits:
        accession = str(hit.metadata.get("accession_number") or hit.chunk_id)
        if per_filing.get(accession, 0) >= 3:
            continue
        per_filing[accession] = per_filing.get(accession, 0) + 1
        selected.append(hit)
        if len(selected) >= top_n:
            break

    # If diversification starved the result set (one filing, many chunks), fall
    # back to plain top-n rather than returning too little context.
    return selected if len(selected) >= min(top_n, len(hits)) // 2 else hits[:top_n]
