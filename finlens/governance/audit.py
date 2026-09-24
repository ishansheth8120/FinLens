"""Append-only audit log.

Every request writes one record: who asked, what they asked, how it was routed,
the exact SQL that ran, how many rows it returned and a hash of them, which
chunks were retrieved, what was answered, whether the numbers reconciled, and
what it cost. `/audit/{request_id}` replays it.

Two design points worth defending:

**Append-only, enforced by the schema.** There is no `UPDATE` path in this
module and the table has no mutable columns. An audit log you can edit is not
an audit log.

**The result hash, not the results.** Storing every row of every query would
grow without bound and would duplicate data that is already in the warehouse.
A SHA-256 over the result set answers the question that actually gets asked in
an incident — "was this the same data we served then?" — at fixed cost. If the
warehouse has been rebuilt since, the hash changes, and that is the correct
answer rather than a false reassurance.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from finlens.config import Settings, get_settings
from finlens.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    import duckdb

log = get_logger(__name__)

TABLE = "request_audit"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    request_id            VARCHAR PRIMARY KEY,
    ts                    TIMESTAMP NOT NULL,
    user_id               VARCHAR NOT NULL,
    user_role             VARCHAR,
    permitted_cik_count   INTEGER,
    question              VARCHAR NOT NULL,
    route                 VARCHAR,
    route_confidence      DOUBLE,
    generated_sql         VARCHAR,
    scoped_sql            VARCHAR,
    sql_tables            VARCHAR,
    sql_error             VARCHAR,
    row_count             INTEGER,
    result_hash           VARCHAR,
    chunk_ids             VARCHAR,
    answer                VARCHAR,
    numeric_claims        INTEGER,
    claims_reconciled     INTEGER,
    claims_failed         INTEGER,
    groundedness          DOUBLE,
    verification_detail   VARCHAR,
    llm_provider          VARCHAR,
    llm_model             VARCHAR,
    prompt_tokens         INTEGER,
    completion_tokens     INTEGER,
    latency_ms            DOUBLE,
    warnings              VARCHAR
)
"""


def new_request_id() -> str:
    return uuid.uuid4().hex


def hash_rows(rows: list[list[Any]] | None) -> str | None:
    """Stable digest of a result set.

    Serialised with `default=str` so dates and decimals hash deterministically
    rather than raising, and without sorting - row order is part of the answer
    for anything ranked.
    """
    if rows is None:
        return None
    payload = json.dumps(rows, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class AuditRecord:
    """One request, in full."""

    request_id: str
    ts: datetime
    user_id: str
    question: str
    user_role: str | None = None
    permitted_cik_count: int | None = None
    route: str | None = None
    route_confidence: float | None = None
    generated_sql: str | None = None
    scoped_sql: str | None = None
    sql_tables: list[str] = field(default_factory=list)
    sql_error: str | None = None
    row_count: int | None = None
    result_hash: str | None = None
    chunk_ids: list[str] = field(default_factory=list)
    answer: str | None = None
    numeric_claims: int = 0
    claims_reconciled: int = 0
    claims_failed: int = 0
    groundedness: float | None = None
    verification_detail: dict[str, Any] = field(default_factory=dict)
    llm_provider: str | None = None
    llm_model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_row(self) -> list[Any]:
        return [
            self.request_id,
            self.ts,
            self.user_id,
            self.user_role,
            self.permitted_cik_count,
            self.question,
            self.route,
            self.route_confidence,
            self.generated_sql,
            self.scoped_sql,
            json.dumps(self.sql_tables),
            self.sql_error,
            self.row_count,
            self.result_hash,
            json.dumps(self.chunk_ids),
            self.answer,
            self.numeric_claims,
            self.claims_reconciled,
            self.claims_failed,
            self.groundedness,
            json.dumps(self.verification_detail, default=str),
            self.llm_provider,
            self.llm_model,
            self.prompt_tokens,
            self.completion_tokens,
            self.latency_ms,
            json.dumps(self.warnings),
        ]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ts"] = self.ts.isoformat()
        return payload


COLUMNS = [
    "request_id", "ts", "user_id", "user_role", "permitted_cik_count", "question",
    "route", "route_confidence", "generated_sql", "scoped_sql", "sql_tables",
    "sql_error", "row_count", "result_hash", "chunk_ids", "answer",
    "numeric_claims", "claims_reconciled", "claims_failed", "groundedness",
    "verification_detail", "llm_provider", "llm_model", "prompt_tokens",
    "completion_tokens", "latency_ms", "warnings",
]  # fmt: skip

_JSON_COLUMNS = {"sql_tables", "chunk_ids", "warnings", "verification_detail"}


class AuditLog:
    """DuckDB-backed append-only log.

    A separate database file from the warehouse on purpose: the warehouse is
    rebuilt by dbt on every run, and an audit log that gets dropped and
    recreated nightly is worthless.
    """

    def __init__(self, path: Path | str | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.path = Path(path) if path else self.settings.duckdb_path.parent / "audit.duckdb"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con: duckdb.DuckDBPyConnection | None = None

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            import duckdb

            self._con = duckdb.connect(str(self.path))
            self._con.execute(SCHEMA)
        return self._con

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    def __enter__(self) -> AuditLog:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- writing --------------------------------------------------------------

    def write(self, record: AuditRecord) -> str:
        """Append a record. Never raises into the request path.

        A failed audit write must not fail the user's request, but it must be
        loud: an unlogged request is a gap in the trail, and silence about it
        would be worse than the gap.
        """
        try:
            placeholders = ", ".join("?" for _ in COLUMNS)
            self.con.execute(
                f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES ({placeholders})",
                record.to_row(),
            )
        except Exception as exc:  # noqa: BLE001
            log.error("audit.write_failed", request_id=record.request_id, error=str(exc))
        return record.request_id

    # -- reading --------------------------------------------------------------

    def get(self, request_id: str) -> dict[str, Any] | None:
        """One record, for replay."""
        cursor = self.con.execute(
            f"SELECT {', '.join(COLUMNS)} FROM {TABLE} WHERE request_id = ?", [request_id]
        )
        row = cursor.fetchone()
        return self._to_dict(row) if row else None

    def recent(self, limit: int = 50, user_id: str | None = None) -> list[dict[str, Any]]:
        where, params = ("WHERE user_id = ?", [user_id]) if user_id else ("", [])
        rows = self.con.execute(
            f"SELECT {', '.join(COLUMNS)} FROM {TABLE} {where} ORDER BY ts DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
        return [self._to_dict(row) for row in rows]

    def failures(self, limit: int = 50) -> list[dict[str, Any]]:
        """Requests where a numeric claim did not reconcile.

        The single most useful query in the log: it is the list of answers the
        system would have got wrong if nothing had been checking.
        """
        rows = self.con.execute(
            f"SELECT {', '.join(COLUMNS)} FROM {TABLE} "
            "WHERE claims_failed > 0 ORDER BY ts DESC LIMIT ?",
            [limit],
        ).fetchall()
        return [self._to_dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        row = self.con.execute(
            f"""
            SELECT
                count(*)                                   AS requests,
                count(DISTINCT user_id)                    AS users,
                avg(latency_ms)                            AS mean_latency_ms,
                quantile_cont(latency_ms, 0.95)            AS p95_latency_ms,
                sum(prompt_tokens + completion_tokens)     AS total_tokens,
                sum(numeric_claims)                        AS claims,
                sum(claims_failed)                         AS claims_failed,
                avg(groundedness)                          AS mean_groundedness
            FROM {TABLE}
            """
        ).fetchone()
        keys = [
            "requests", "users", "mean_latency_ms", "p95_latency_ms",
            "total_tokens", "claims", "claims_failed", "mean_groundedness",
        ]  # fmt: skip
        return dict(zip(keys, row))

    def _to_dict(self, row: tuple[Any, ...]) -> dict[str, Any]:
        record = dict(zip(COLUMNS, row))
        for column in _JSON_COLUMNS:
            value = record.get(column)
            if isinstance(value, str):
                try:
                    record[column] = json.loads(value)
                except json.JSONDecodeError:
                    pass
        if isinstance(record.get("ts"), datetime):
            record["ts"] = record["ts"].isoformat()
        return record


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
