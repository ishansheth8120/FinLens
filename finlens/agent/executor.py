"""Running validated SQL against the warehouse.

The connection is opened **read-only**. That, not the regex guard in
`sql_guard`, is the actual security boundary: DuckDB will refuse a write on a
read-only connection regardless of how the statement is spelled or what the
parser was fooled into thinking.

Two further limits, because read-only says nothing about cost: a wall-clock
timeout enforced by interrupting the connection from a watchdog thread, and the
row cap the guard already injected.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from finlens.agent.sql_guard import GuardResult, validate
from finlens.agent.types import SqlResult
from finlens.config import Settings, get_settings
from finlens.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    import duckdb

log = get_logger(__name__)


class SqlExecutor:
    """Read-only query execution against the DuckDB warehouse."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.path = Path(self.settings.duckdb_path)
        self._con: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.Lock()

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            import duckdb

            if not self.path.exists():
                raise FileNotFoundError(
                    f"no warehouse at {self.path} - run `make warehouse` to build it"
                )
            self._con = duckdb.connect(str(self.path), read_only=True)
        return self._con

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    def __enter__(self) -> SqlExecutor:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- execution ------------------------------------------------------------

    def execute(self, sql: str, *, explanation: str | None = None) -> SqlResult:
        """Validate then run a query, returning results or a usable error.

        Never raises for a bad query. A syntax error is information the SQL
        generator can repair on a retry, so it comes back in `SqlResult.error`
        rather than as an exception.
        """
        guard: GuardResult = validate(sql, row_limit=self.settings.sql_row_limit)
        if not guard.ok:
            return SqlResult(
                sql=sql,
                error=f"query rejected: {'; '.join(guard.errors)}",
                explanation=explanation,
            )

        started = time.perf_counter()
        try:
            rows, columns = self._run_with_timeout(guard.sql)
        except TimeoutError:
            return SqlResult(
                sql=guard.sql,
                error=f"query exceeded the {self.settings.sql_timeout_s:.0f}s timeout",
                explanation=explanation,
                elapsed_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the repair loop
            return SqlResult(
                sql=guard.sql,
                error=str(exc),
                explanation=explanation,
                elapsed_ms=(time.perf_counter() - started) * 1000,
            )

        elapsed_ms = (time.perf_counter() - started) * 1000
        log.info("sql.executed", rows=len(rows), elapsed_ms=round(elapsed_ms, 1))

        return SqlResult(
            sql=guard.sql,
            columns=columns,
            rows=[list(row) for row in rows],
            row_count=len(rows),
            truncated=len(rows) >= self.settings.sql_row_limit,
            elapsed_ms=elapsed_ms,
            explanation=explanation,
        )

    def _run_with_timeout(self, sql: str) -> tuple[list[tuple[Any, ...]], list[str]]:
        """Run a query, interrupting it if it overruns.

        DuckDB has no per-statement timeout, so a watchdog calls `interrupt()`
        on the connection. The lock serialises access because the cursor is
        shared and interrupting the wrong query would be worse than slow.
        """
        with self._lock:
            timer = threading.Timer(self.settings.sql_timeout_s, self.con.interrupt)
            timer.start()
            try:
                cursor = self.con.execute(sql)
                columns = [d[0] for d in cursor.description or []]
                rows = cursor.fetchall()
            except Exception as exc:
                if not timer.is_alive():
                    # The watchdog already fired; the real cause is the timeout.
                    raise TimeoutError from exc
                raise
            finally:
                timer.cancel()
        return rows, columns

    # -- introspection --------------------------------------------------------

    def table_names(self) -> list[str]:
        rows = self.con.execute(
            """
            SELECT table_schema || '.' || table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY 1
            """
        ).fetchall()
        return [r[0] for r in rows]

    def sample(self, table: str, limit: int = 5) -> SqlResult:
        """A few rows from one table, for schema-catalogue value examples."""
        return self.execute(f"SELECT * FROM {table} LIMIT {limit}")
