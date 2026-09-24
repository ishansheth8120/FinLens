"""Validation for model-generated SQL, as a real control rather than decoration.

Parsed with `sqlglot`, not matched with regexes. The difference matters: a regex
that looks for the word `delete` rejects `WHERE company_name = 'Delete Inc.'`
and accepts `SEL/**/ECT`. An AST answers the actual questions — what kind of
statement is this, which tables does it touch — and answers them the way the
database will.

Three controls, in order of importance:

1. **Table allowlist.** Generated SQL may read the `mart_` layer and nothing
   else. Not staging, not raw, not `information_schema`. This is why the marts
   are narrow: the LLM's blast radius is exactly the tables listed here.
2. **Read-only.** Anything that is not a `SELECT`/`WITH` is rejected outright.
3. **Bounded.** A row limit is injected when absent and clamped when excessive.

The database connection is *also* opened read-only. This layer exists to reject
bad queries with a usable error before they run, and to catch the
expensive-but-legal ones a read-only flag says nothing about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from finlens.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    import sqlglot

log = get_logger(__name__)

DIALECT = "duckdb"

# The only tables generated SQL may read. Everything here is a dbt mart with a
# documented, tested schema; nothing here exposes an un-deduplicated fact.
ALLOWED_TABLES: frozenset[str] = frozenset(
    {
        "dim_company",
        "dim_filing",
        "fct_financial_fact",
        "fct_company_metric",
        "fct_company_annual",
        "fct_filing_section",
        "metric_definitions",
    }
)

ALLOWED_SCHEMAS: frozenset[str] = frozenset({"main_marts", "main_semantic", "main", ""})

# Functions that read or write outside the database.
FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {
        "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto",
        "read_text", "read_blob", "glob", "parquet_scan", "csv_scan", "sniff_csv",
        "shell", "system", "getenv", "load_extension", "install_extension",
    }
)  # fmt: skip


class SqlGuardError(ValueError):
    """The query was rejected."""


@dataclass
class GuardResult:
    ok: bool
    sql: str
    tables: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def raise_if_blocked(self) -> str:
        if not self.ok:
            raise SqlGuardError("; ".join(self.errors))
        return self.sql


def _parse(sql: str) -> list[sqlglot.Expression]:
    import sqlglot

    return [s for s in sqlglot.parse(sql, dialect=DIALECT) if s is not None]


def referenced_tables(sql: str) -> set[str]:
    """Every table the query reads, as ``schema.name`` (schema may be empty).

    CTE names are excluded — they are local aliases, not tables, and treating
    them as tables would reject every non-trivial query.
    """
    import sqlglot
    from sqlglot import exp

    try:
        statements = _parse(sql)
    except sqlglot.ParseError:
        return set()

    tables: set[str] = set()
    for statement in statements:
        cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
        for table in statement.find_all(exp.Table):
            name = (table.name or "").lower()
            if not name or name in cte_names:
                continue
            schema = (table.db or "").lower()
            tables.add(f"{schema}.{name}" if schema else name)
    return tables


def _called_functions(statement: sqlglot.Expression) -> set[str]:
    from sqlglot import exp

    names: set[str] = set()
    for node in statement.find_all(exp.Anonymous):
        if node.this:
            names.add(str(node.this).lower())
    for node in statement.find_all(exp.Func):
        name = node.sql_name() if hasattr(node, "sql_name") else type(node).__name__
        names.add(str(name).lower())
    return names


def validate(
    sql: str,
    *,
    row_limit: int = 1000,
    allowed_tables: frozenset[str] = ALLOWED_TABLES,
) -> GuardResult:
    """Parse, authorise and bound a generated query."""
    import sqlglot
    from sqlglot import exp

    if not sql or not sql.strip():
        return GuardResult(ok=False, sql=sql, errors=["empty query"])

    try:
        statements = _parse(sql)
    except sqlglot.ParseError as exc:
        return GuardResult(ok=False, sql=sql, errors=[f"could not parse: {exc}"])

    if len(statements) != 1:
        return GuardResult(
            ok=False,
            sql=sql,
            errors=[f"expected exactly one statement, found {len(statements)}"],
        )

    statement = statements[0]
    errors: list[str] = []
    warnings: list[str] = []

    # --- 1. must be a read ---------------------------------------------------
    # `WITH` parses as a Select carrying a `with` clause, so checking for Select
    # covers both forms.
    if not isinstance(statement, exp.Select):
        errors.append(
            f"only SELECT queries are permitted, got {type(statement).__name__.upper()}"
        )

    # Belt and braces: an explicit scan for mutating nodes, in case a dialect
    # quirk lets one hide inside a Select.
    mutating = (
        exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
        exp.Alter, exp.Command, exp.Pragma, exp.Set, exp.Attach,
    )  # fmt: skip
    for node_type in mutating:
        if statement.find(node_type):
            errors.append(f"forbidden statement type: {node_type.__name__.upper()}")

    # --- 2. table allowlist --------------------------------------------------
    tables = referenced_tables(sql)
    for qualified in sorted(tables):
        schema, _, name = qualified.rpartition(".")
        if name not in allowed_tables:
            errors.append(
                f"table not permitted: {qualified} "
                f"(allowed: {', '.join(sorted(allowed_tables))})"
            )
        elif schema not in ALLOWED_SCHEMAS:
            errors.append(f"schema not permitted: {schema}")

    if not tables and isinstance(statement, exp.Select):
        # A constant SELECT reads nothing, which is harmless but never a real
        # answer - worth flagging so the caller can retry rather than serve it.
        warnings.append("query reads no tables")

    # --- 3. function allowlist -----------------------------------------------
    for function in sorted(_called_functions(statement) & FORBIDDEN_FUNCTIONS):
        errors.append(f"forbidden function: {function}()")

    if errors:
        log.warning("sql_guard.rejected", errors=errors, tables=sorted(tables))
        return GuardResult(ok=False, sql=sql, tables=tables, errors=errors, warnings=warnings)

    # --- 4. bound the result -------------------------------------------------
    guarded = _apply_limit(statement, row_limit, warnings)

    return GuardResult(ok=True, sql=guarded, tables=tables, warnings=warnings)


def _apply_limit(statement: sqlglot.Expression, row_limit: int, warnings: list[str]) -> str:
    """Inject or clamp the row limit, on the AST rather than the text.

    A missing `LIMIT` is not an error - it is the single most common omission in
    generated SQL, and rejecting an otherwise-perfect query for it would be a
    poor trade. Adding one is strictly better.
    """
    from sqlglot import exp

    existing = statement.args.get("limit")
    if existing is None:
        statement.set("limit", exp.Limit(expression=exp.Literal.number(row_limit)))
        warnings.append(f"no LIMIT in generated query; applied LIMIT {row_limit}")
    else:
        try:
            current = int(existing.expression.name)
        except (AttributeError, ValueError):
            current = row_limit + 1  # unparseable limit - clamp it
        if current > row_limit:
            statement.set("limit", exp.Limit(expression=exp.Literal.number(row_limit)))
            warnings.append(f"LIMIT {current} exceeded the cap; reduced to {row_limit}")

    return statement.sql(dialect=DIALECT, pretty=True)


def explain_allowlist() -> str:
    """Human-readable control description, for the report and the audit log."""
    return (
        "Generated SQL is parsed with sqlglot and must be a single SELECT reading "
        f"only: {', '.join(sorted(ALLOWED_TABLES))}. Filesystem and extension "
        "functions are blocked, a row limit is enforced, and the database "
        "connection is opened read-only."
    )
