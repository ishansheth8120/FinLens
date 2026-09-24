"""The vector index, on DuckDB.

DuckDB rather than a dedicated vector database, for three reasons that matter
more here than raw ANN throughput:

1. **The metadata filters are the hard part.** Almost every real question is
   scoped - "Apple's risk factors in 2023", not "risk factors". Pre-filtering to
   a few hundred candidates and then scoring exactly beats an approximate search
   over millions followed by a post-filter that throws most results away.
2. **The warehouse is already DuckDB.** One engine, one file, and the index can
   join directly against `fct_filing_section` for citations.
3. **Hybrid search comes free.** DuckDB's FTS extension gives BM25 in the same
   query engine, and lexical matching is not optional in this domain - exact
   tickers, section numbers and dollar figures are precisely what dense
   retrieval is worst at.

The `vss` extension provides an HNSW index for when exact scoring stops being
fast enough; `create_ann_index` turns it on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from finlens.config import Settings, get_settings
from finlens.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    import duckdb

log = get_logger(__name__)

TABLE = "chunk_index"

# Columns carried on the index itself so a filtered search never needs a join.
METADATA_COLUMNS: list[tuple[str, str]] = [
    ("section_id", "VARCHAR"),
    ("cik", "VARCHAR"),
    ("ticker", "VARCHAR"),
    ("company_name", "VARCHAR"),
    ("accession_number", "VARCHAR"),
    ("form", "VARCHAR"),
    ("filing_date", "DATE"),
    ("fiscal_year", "INTEGER"),
    ("item", "VARCHAR"),
    ("section_title", "VARCHAR"),
    ("citation_label", "VARCHAR"),
    ("ordinal", "INTEGER"),
    ("token_estimate", "INTEGER"),
]


@dataclass
class SearchHit:
    chunk_id: str
    text: str
    score: float
    metadata: dict[str, Any]

    @property
    def citation(self) -> str:
        return str(self.metadata.get("citation_label") or self.metadata.get("cik") or "unknown")


@dataclass
class Filters:
    """Metadata predicates applied before scoring."""

    ciks: list[str] | None = None
    tickers: list[str] | None = None
    forms: list[str] | None = None
    items: list[str] | None = None
    fiscal_year_min: int | None = None
    fiscal_year_max: int | None = None

    def to_sql(self, prefix: str = "") -> tuple[str, list[Any]]:
        """Render as a WHERE fragment plus positional parameters.

        Parameterised rather than interpolated: these values come from an LLM's
        entity extraction, and a ticker is a string the model chose. ``prefix``
        qualifies the column names for queries that join (e.g. ``"t."``).
        """
        clauses: list[str] = []
        params: list[Any] = []

        for column, values in (
            ("cik", self.ciks),
            ("ticker", self.tickers),
            ("form", self.forms),
            ("item", self.items),
        ):
            if values:
                placeholders = ", ".join("?" for _ in values)
                clauses.append(f"{prefix}{column} IN ({placeholders})")
                params.extend(values)

        if self.fiscal_year_min is not None:
            clauses.append(f"{prefix}fiscal_year >= ?")
            params.append(self.fiscal_year_min)
        if self.fiscal_year_max is not None:
            clauses.append(f"{prefix}fiscal_year <= ?")
            params.append(self.fiscal_year_max)

        return (" AND ".join(clauses) if clauses else "TRUE"), params


class VectorStore:
    """Read/write access to the chunk index."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        dim: int | None = None,
        settings: Settings | None = None,
        read_only: bool = False,
    ) -> None:
        self.settings = settings or get_settings()
        self.dim = dim or self.settings.embedding_dim
        self.path = Path(path or self.settings.vector_store_path) / "chunks.duckdb"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._read_only = read_only
        self._con: duckdb.DuckDBPyConnection | None = None

    # -- connection -----------------------------------------------------------

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            import duckdb

            self._con = duckdb.connect(str(self.path), read_only=self._read_only)
            self._con.execute("INSTALL fts; LOAD fts;")
        return self._con

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    def __enter__(self) -> VectorStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- schema ---------------------------------------------------------------

    def create(self, *, drop_existing: bool = False) -> None:
        if drop_existing:
            self.con.execute(f"DROP TABLE IF EXISTS {TABLE}")

        columns = ",\n            ".join(f"{name} {sql_type}" for name, sql_type in METADATA_COLUMNS)
        self.con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
            chunk_id VARCHAR PRIMARY KEY,
            {columns},
            text VARCHAR NOT NULL,
            embedding FLOAT[{self.dim}]
            )
            """
        )
        log.info("vector_store.ready", path=str(self.path), dim=self.dim)

    def create_fts_index(self) -> None:
        """Build the BM25 index. Must be rebuilt after every bulk load."""
        # `overwrite=1`, not `:=` - the FTS pragma takes plain named arguments.
        self.con.execute(f"PRAGMA create_fts_index('{TABLE}', 'chunk_id', 'text', overwrite=1)")
        log.info("vector_store.fts_index_built")

    def create_ann_index(self) -> None:
        """Build an HNSW index via the `vss` extension.

        Optional. Exact scoring over a filtered candidate set is fast well into
        the millions of chunks; this is for when it stops being.
        """
        self.con.execute("INSTALL vss; LOAD vss;")
        self.con.execute("SET hnsw_enable_experimental_persistence = true;")
        self.con.execute(
            f"CREATE INDEX IF NOT EXISTS {TABLE}_hnsw ON {TABLE} "
            f"USING HNSW (embedding) WITH (metric = 'cosine')"
        )
        log.info("vector_store.ann_index_built")

    def _has_fts(self) -> bool:
        rows = self.con.execute(
            "SELECT 1 FROM duckdb_schemas() WHERE schema_name = ?", [f"fts_main_{TABLE}"]
        ).fetchall()
        return bool(rows)

    # -- writing --------------------------------------------------------------

    def upsert(self, rows: list[dict[str, Any]]) -> int:
        """Insert or replace chunk rows.

        ``rows`` need an ``chunk_id``, ``text`` and ``embedding``; any of the
        metadata columns may be present and the rest default to NULL.
        """
        if not rows:
            return 0

        columns = ["chunk_id", *[c for c, _ in METADATA_COLUMNS], "text", "embedding"]
        placeholders = ", ".join("?" for _ in columns)
        values = [[row.get(column) for column in columns] for row in rows]

        self.con.executemany(
            f"INSERT OR REPLACE INTO {TABLE} ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        return len(values)

    def count(self) -> int:
        return int(self.con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0])

    # -- searching ------------------------------------------------------------

    def vector_search(
        self, query_vector: list[float], *, top_k: int = 24, filters: Filters | None = None
    ) -> list[SearchHit]:
        """Exact cosine search over the filtered candidate set."""
        where, params = (filters or Filters()).to_sql()
        columns = ", ".join(c for c, _ in METADATA_COLUMNS)

        sql = f"""
            SELECT chunk_id, text, {columns},
                   array_cosine_similarity(embedding, ?::FLOAT[{self.dim}]) AS score
            FROM {TABLE}
            WHERE {where} AND embedding IS NOT NULL
            ORDER BY score DESC
            LIMIT ?
        """
        rows = self.con.execute(sql, [query_vector, *params, top_k]).fetchall()
        return self._to_hits(rows)

    def keyword_search(
        self, query: str, *, top_k: int = 24, filters: Filters | None = None
    ) -> list[SearchHit]:
        """BM25 search. Returns nothing rather than raising if no FTS index exists."""
        if not self._has_fts():
            log.warning("vector_store.no_fts_index", detail="run create_fts_index() first")
            return []

        where, params = (filters or Filters()).to_sql(prefix="t.")
        columns = ", ".join(f"t.{c}" for c, _ in METADATA_COLUMNS)

        sql = f"""
            WITH scored AS (
                SELECT chunk_id, fts_main_{TABLE}.match_bm25(chunk_id, ?) AS score
                FROM {TABLE}
            )
            SELECT t.chunk_id, t.text, {columns}, s.score
            FROM scored s
            JOIN {TABLE} t USING (chunk_id)
            WHERE s.score IS NOT NULL AND {where}
            ORDER BY s.score DESC
            LIMIT ?
        """
        rows = self.con.execute(sql, [query, *params, top_k]).fetchall()
        return self._to_hits(rows)

    def hybrid_search(
        self,
        query: str,
        query_vector: list[float],
        *,
        top_k: int = 24,
        filters: Filters | None = None,
        rrf_k: int = 60,
    ) -> list[SearchHit]:
        """Reciprocal rank fusion of dense and lexical results.

        RRF rather than a weighted score blend because BM25 scores and cosine
        similarities are not on comparable scales, and the weighting that works
        for one query length fails for another. RRF only uses ranks, so it needs
        no per-corpus tuning. ``rrf_k=60`` is the value from the original paper
        and has held up here.
        """
        # Over-fetch from each arm: a chunk ranked 30th densely and 5th lexically
        # should still surface, and it cannot if we only look at each arm's top-k.
        fetch = top_k * 3
        dense = self.vector_search(query_vector, top_k=fetch, filters=filters)
        lexical = self.keyword_search(query, top_k=fetch, filters=filters)

        fused: dict[str, float] = {}
        hits: dict[str, SearchHit] = {}
        for ranking in (dense, lexical):
            for rank, hit in enumerate(ranking, start=1):
                fused[hit.chunk_id] = fused.get(hit.chunk_id, 0.0) + 1.0 / (rrf_k + rank)
                hits.setdefault(hit.chunk_id, hit)

        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        return [
            SearchHit(
                chunk_id=chunk_id,
                text=hits[chunk_id].text,
                score=score,
                metadata=hits[chunk_id].metadata,
            )
            for chunk_id, score in ordered
        ]

    def _to_hits(self, rows: list[tuple[Any, ...]]) -> list[SearchHit]:
        names = [c for c, _ in METADATA_COLUMNS]
        hits: list[SearchHit] = []
        for row in rows:
            chunk_id, text, *rest = row
            *metadata_values, score = rest
            hits.append(
                SearchHit(
                    chunk_id=chunk_id,
                    text=text,
                    score=float(score) if score is not None else 0.0,
                    metadata=dict(zip(names, metadata_values)),
                )
            )
        return hits
