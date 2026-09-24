"""Entity-level access control.

The requirement: two analysts ask the identical question and get different
answers, because they are permitted different companies. Coverage restrictions
like this are ordinary in a bank — desk-level entity permissioning, research
walls, restricted lists — and they cannot be implemented by telling the model
which companies to avoid. A prompt is not a control.

So the scope is enforced in two places the model cannot reach:

**The warehouse.** Every generated query is rewritten before execution: each
entity-scoped table reference becomes a subquery filtered to the principal's
permitted CIKs. The model never sees the filter and cannot remove it, and the
rewrite happens on the AST, so it survives joins, CTEs and subqueries.

**The vector store.** Postgres row-level security on `filing_chunks`, keyed to
the connection's role. See `sql/rls.sql` — the database refuses the rows, which
means a bug in this Python cannot leak them.

The two mechanisms differ because the stores differ, and that is worth being
explicit about: RLS is the stronger control, and the SQL rewrite is what you do
when the engine has no RLS (DuckDB does not). On BigQuery the equivalent is an
authorised view, which is the same idea with the rewrite done once at deploy
time instead of per query.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from finlens.identifiers import normalize_cik
from finlens.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    pass

log = get_logger(__name__)

DIALECT = "duckdb"

# Tables carrying a `cik` column, and therefore scopable. Anything not listed
# is reference data with no entity dimension (`metric_definitions`), which is
# readable by everyone.
ENTITY_SCOPED_TABLES: frozenset[str] = frozenset(
    {
        "dim_company",
        "dim_filing",
        "fct_financial_fact",
        "fct_company_metric",
        "fct_company_annual",
        "fct_filing_section",
    }
)

# The wildcard. Held by admins and by the single-tenant default deployment.
ALL_ENTITIES = "*"


class Role(str, Enum):
    ADMIN = "admin"
    """Unrestricted. Sees every company."""

    ANALYST = "analyst"
    """Restricted to an explicit CIK list."""

    READONLY = "readonly"
    """Restricted, and additionally barred from the audit log."""


@dataclass(frozen=True)
class Principal:
    """Who is asking."""

    user_id: str
    role: Role = Role.ANALYST
    permitted_ciks: frozenset[str] = field(default_factory=frozenset)
    display_name: str = ""

    @classmethod
    def admin(cls, user_id: str = "admin") -> Principal:
        return cls(user_id=user_id, role=Role.ADMIN, permitted_ciks=frozenset({ALL_ENTITIES}))

    @classmethod
    def analyst(cls, user_id: str, ciks: list[str | int], display_name: str = "") -> Principal:
        return cls(
            user_id=user_id,
            role=Role.ANALYST,
            permitted_ciks=frozenset(normalize_cik(c) for c in ciks),
            display_name=display_name,
        )

    @property
    def unrestricted(self) -> bool:
        return self.role == Role.ADMIN or ALL_ENTITIES in self.permitted_ciks

    @property
    def may_read_audit(self) -> bool:
        return self.role in (Role.ADMIN, Role.ANALYST)

    def may_access(self, cik: str | int) -> bool:
        return self.unrestricted or normalize_cik(cik) in self.permitted_ciks

    def scope_description(self) -> str:
        if self.unrestricted:
            return "all companies"
        return f"{len(self.permitted_ciks)} permitted companies"


@dataclass
class AccessPolicy:
    """The scoping rules applied to one principal's requests."""

    principal: Principal
    scoped_tables: frozenset[str] = ENTITY_SCOPED_TABLES

    @property
    def permitted_ciks(self) -> list[str]:
        return sorted(self.principal.permitted_ciks)

    def filter_ciks(self, ciks: list[str]) -> list[str]:
        """Narrow a requested CIK list to what the principal may see."""
        if self.principal.unrestricted:
            return ciks
        return [c for c in ciks if self.principal.may_access(c)]

    def retrieval_ciks(self, requested: list[str] | None) -> list[str] | None:
        """The CIK filter to apply to a vector search.

        Returns `None` for an unrestricted principal with no request-level
        filter, meaning "no predicate". For a restricted principal it always
        returns a list — including an empty one, which correctly matches
        nothing rather than silently matching everything.
        """
        if self.principal.unrestricted:
            return requested or None
        permitted = self.permitted_ciks
        if not requested:
            return permitted
        return [c for c in requested if c in set(permitted)]


class AccessDenied(PermissionError):
    """The request cannot be served within the principal's scope."""


def scope_sql(
    sql: str,
    policy: AccessPolicy,
    *,
    dialect: str = DIALECT,
) -> str:
    """Rewrite a query so it can only read the principal's permitted entities.

    Each entity-scoped table reference is replaced with a filtered subquery::

        FROM marts.fct_company_annual a
          ->
        FROM (SELECT * FROM marts.fct_company_annual
              WHERE cik IN ('0000320193')) AS a

    Done on the AST, so it applies inside CTEs, subqueries and every join arm,
    and it preserves the alias the rest of the query refers to. A model that
    writes `WHERE cik = '0000789019'` for a company it may not see gets an
    empty result, not a leak.
    """
    if policy.principal.unrestricted:
        return sql

    import sqlglot
    from sqlglot import exp

    permitted = policy.permitted_ciks
    statement = sqlglot.parse_one(sql, dialect=dialect)

    # CTE names are local aliases, not tables - rewriting them would produce a
    # reference to a table that does not exist.
    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}

    def rewrite(node: exp.Expression) -> exp.Expression:
        if not isinstance(node, exp.Table):
            return node
        name = (node.name or "").lower()
        if name in cte_names or name not in policy.scoped_tables:
            return node

        alias = node.alias or node.name
        values = (
            ", ".join(f"'{c}'" for c in permitted)
            # An empty permitted set must match nothing. `IN ()` is a syntax
            # error in most dialects, so use a predicate that is always false.
            if permitted
            else "NULL"
        )
        qualified = f"{node.db}.{node.name}" if node.db else node.name
        subquery = sqlglot.parse_one(
            f"(SELECT * FROM {qualified} WHERE cik IN ({values}))", dialect=dialect
        )
        return exp.Subquery(this=subquery.this, alias=exp.TableAlias(this=exp.to_identifier(alias)))

    scoped = statement.transform(rewrite)
    rewritten = scoped.sql(dialect=dialect, pretty=True)

    log.info(
        "access.scoped_query",
        user=policy.principal.user_id,
        permitted=len(permitted),
    )
    return rewritten


def describe_control() -> str:
    """Control description for the audit log and the report."""
    return (
        "Entity scope is enforced by AST rewrite on every generated query "
        "(each scoped table becomes a CIK-filtered subquery) and by Postgres "
        "row-level security on the vector store. The model never sees the "
        "filter and cannot remove it."
    )
