"""Supabase Postgres + pgvector backend.

The same interface as the DuckDB store, with one important difference: search
runs through the `search_chunks` SQL function, which is `security invoker`, so
Postgres row-level security applies to the querying role. Entity scope is
enforced by the database rather than by this file — which means a bug here
cannot leak a company the user is not entitled to.

Loading uses the service role and deliberately bypasses RLS; reading uses the
authenticated role and does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from finlens.config import Settings, get_settings
from finlens.embed.store import Filters, SearchHit
from finlens.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    import psycopg

log = get_logger(__name__)

RLS_SQL = Path(__file__).parent.parent / "governance" / "sql" / "rls.sql"

UPSERT = """
INSERT INTO filing_chunks (
    chunk_id, section_id, cik, ticker, company_name, accession, form,
    filing_date, fiscal_year, item_section, heading_path, citation_label,
    chunk_index, token_estimate, content, source_url, embedding
) VALUES (
    %(chunk_id)s, %(section_id)s, %(cik)s, %(ticker)s, %(company_name)s,
    %(accession)s, %(form)s, %(filing_date)s, %(fiscal_year)s, %(item_section)s,
    %(heading_path)s, %(citation_label)s, %(chunk_index)s, %(token_estimate)s,
    %(content)s, %(source_url)s, %(embedding)s
)
ON CONFLICT (chunk_id) DO UPDATE SET
    content    = EXCLUDED.content,
    embedding  = EXCLUDED.embedding,
    created_at = now()
"""

SEARCH = """
SELECT chunk_id, cik, ticker, fiscal_year, item_section,
       citation_label, content, source_url, score
FROM search_chunks(
    %(embedding)s, %(query)s, %(limit)s, %(rrf_k)s,
    %(ciks)s, %(items)s, %(year_min)s, %(year_max)s
)
"""


@dataclass
class PgVectorStore:
    """pgvector-backed chunk index."""

    dsn: str
    dim: int = 384
    _conn: Any = None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> PgVectorStore:
        settings = settings or get_settings()
        if not settings.supabase_db_url:
            raise RuntimeError(
                "FINLENS_VECTOR_BACKEND=pgvector but SUPABASE_DB_URL is unset. "
                "Get it from Supabase -> Project Settings -> Database -> Connection string."
            )
        return cls(
            dsn=settings.supabase_db_url.get_secret_value(),
            dim=settings.embedding_dim,
        )

    @property
    def conn(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            try:
                import psycopg
                from pgvector.psycopg import register_vector
            except ImportError as exc:  # pragma: no cover - depends on extras
                raise RuntimeError(
                    "the pgvector backend needs `pip install 'finlens[pgvector]'`"
                ) from exc

            self._conn = psycopg.connect(self.dsn, autocommit=True)
            register_vector(self._conn)
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None

    def __enter__(self) -> PgVectorStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- schema ---------------------------------------------------------------

    def apply_schema(self) -> None:
        """Run `rls.sql`. Idempotent; safe to re-run on every deploy."""
        sql = RLS_SQL.read_text(encoding="utf-8")
        with self.conn.cursor() as cur:
            cur.execute(sql)
        log.info("pgvector.schema_applied", path=str(RLS_SQL))

    # -- writing --------------------------------------------------------------

    def upsert(self, rows: list[dict[str, Any]]) -> int:
        """Bulk insert. Run as the service role, which bypasses RLS."""
        if not rows:
            return 0

        payload = [
            {
                "chunk_id": r["chunk_id"],
                "section_id": r.get("section_id"),
                "cik": r.get("cik"),
                "ticker": r.get("ticker"),
                "company_name": r.get("company_name"),
                "accession": r.get("accession_number"),
                "form": r.get("form"),
                "filing_date": r.get("filing_date"),
                "fiscal_year": r.get("fiscal_year"),
                "item_section": r.get("item"),
                "heading_path": r.get("section_title"),
                "citation_label": r.get("citation_label"),
                "chunk_index": r.get("ordinal", 0),
                "token_estimate": r.get("token_estimate"),
                "content": r["text"],
                "source_url": r.get("source_url") or "",
                "embedding": r.get("embedding"),
            }
            for r in rows
        ]
        with self.conn.cursor() as cur:
            cur.executemany(UPSERT, payload)
        return len(payload)

    def count(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM filing_chunks")
            return int(cur.fetchone()[0])

    def build_ann_index(self) -> None:
        """(Re)build the HNSW index after a bulk load.

        Dropped first: incremental insertion into an HNSW graph during a load is
        an order of magnitude slower than one build at the end.
        """
        with self.conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS filing_chunks_embedding_idx")
            cur.execute(
                "CREATE INDEX filing_chunks_embedding_idx "
                "ON filing_chunks USING hnsw (embedding vector_cosine_ops)"
            )
        log.info("pgvector.ann_index_built")

    # -- searching ------------------------------------------------------------

    def hybrid_search(
        self,
        query: str,
        query_vector: list[float],
        *,
        top_k: int = 20,
        filters: Filters | None = None,
        rrf_k: int = 60,
    ) -> list[SearchHit]:
        """Dense + lexical, fused in the database, under RLS."""
        filters = filters or Filters()
        params = {
            "embedding": query_vector,
            "query": query,
            "limit": top_k,
            "rrf_k": rrf_k,
            "ciks": filters.ciks,
            "items": filters.items,
            "year_min": filters.fiscal_year_min,
            "year_max": filters.fiscal_year_max,
        }
        with self.conn.cursor() as cur:
            cur.execute(SEARCH, params)
            rows = cur.fetchall()

        return [
            SearchHit(
                chunk_id=row[0],
                text=row[6],
                score=float(row[8]),
                metadata={
                    "cik": row[1],
                    "ticker": row[2],
                    "fiscal_year": row[3],
                    "item": row[4],
                    "citation_label": row[5],
                    "source_url": row[7],
                },
            )
            for row in rows
        ]

    def vector_search(
        self, query_vector: list[float], *, top_k: int = 20, filters: Filters | None = None
    ) -> list[SearchHit]:
        """Dense only. Mostly for ablation in the eval - hybrid is the default."""
        return self.hybrid_search("", query_vector, top_k=top_k, filters=filters)


def get_vector_store(settings: Settings | None = None):
    """The configured vector backend.

    Returns the DuckDB store or the pgvector store; both satisfy the subset of
    the interface the RAG path uses (`hybrid_search`, `vector_search`, `count`).
    """
    settings = settings or get_settings()

    if settings.vector_backend == "pgvector":
        return PgVectorStore.from_settings(settings)

    from finlens.embed.store import VectorStore

    return VectorStore(settings=settings, read_only=True)
