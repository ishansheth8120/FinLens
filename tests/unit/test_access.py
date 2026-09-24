"""Access scoping is a security control, so the tests are adversarial.

The question each one asks: can a restricted principal get at a company they are
not permitted, by writing the query a certain way?
"""

from __future__ import annotations

import pytest

from finlens.agent.sql_guard import validate
from finlens.governance.access import (
    AccessPolicy,
    Principal,
    Role,
    scope_sql,
)

APPLE = "0000320193"
MSFT = "0000789019"


@pytest.fixture
def restricted() -> AccessPolicy:
    """An analyst permitted Apple only."""
    return AccessPolicy(principal=Principal.analyst("analyst-1", [APPLE]))


@pytest.fixture
def unrestricted() -> AccessPolicy:
    return AccessPolicy(principal=Principal.admin())


# --- principals --------------------------------------------------------------


def test_admin_is_unrestricted():
    admin = Principal.admin()
    assert admin.unrestricted
    assert admin.may_access(MSFT)


def test_analyst_is_restricted_to_their_list():
    analyst = Principal.analyst("a", [APPLE])
    assert not analyst.unrestricted
    assert analyst.may_access(APPLE)
    assert not analyst.may_access(MSFT)


def test_cik_spelling_does_not_defeat_the_check():
    analyst = Principal.analyst("a", [320193])
    assert analyst.may_access("0000320193")
    assert analyst.may_access(320193)


def test_readonly_cannot_read_the_audit_log():
    assert not Principal(user_id="r", role=Role.READONLY).may_read_audit
    assert Principal.admin().may_read_audit


# --- query rewriting ---------------------------------------------------------


def test_unrestricted_queries_are_untouched(unrestricted):
    sql = "SELECT cik FROM marts.dim_company"
    assert scope_sql(sql, unrestricted) == sql


def test_scoped_table_gains_a_cik_filter(restricted):
    scoped = scope_sql("SELECT cik FROM marts.dim_company", restricted)
    assert APPLE in scoped
    assert "cik IN" in scoped.replace("\n", " ")


def test_the_filter_survives_a_join(restricted):
    sql = """
        SELECT c.ticker, a.revenue
        FROM marts.fct_company_annual a
        JOIN marts.dim_company c ON c.cik = a.cik
    """
    scoped = scope_sql(sql, restricted)
    # Both arms of the join must be filtered, not just the first.
    assert scoped.count(APPLE) == 2


def test_the_filter_reaches_inside_a_cte(restricted):
    sql = """
        WITH ranked AS (
            SELECT cik, revenue FROM marts.fct_company_annual
        )
        SELECT * FROM ranked
    """
    scoped = scope_sql(sql, restricted)
    assert APPLE in scoped


def test_the_filter_reaches_inside_a_subquery(restricted):
    sql = "SELECT * FROM (SELECT cik FROM marts.fct_company_metric) x"
    assert APPLE in scope_sql(sql, restricted)


def test_aliases_are_preserved(restricted):
    # If the alias were dropped, every column reference in the outer query
    # would fail to resolve.
    scoped = scope_sql("SELECT a.cik FROM marts.dim_company a", restricted)
    assert " AS a" in scoped or " a" in scoped
    assert "a.cik" in scoped


def test_a_cte_name_is_not_rewritten_as_a_table(restricted):
    # `dim_company` here is a CTE, not the mart. Rewriting it would produce a
    # reference to a table that does not exist.
    sql = """
        WITH dim_company AS (SELECT '1' AS cik)
        SELECT cik FROM dim_company
    """
    scoped = scope_sql(sql, restricted)
    assert "marts.dim_company" not in scoped


def test_reference_tables_are_not_scoped(restricted):
    # `metric_definitions` has no cik column; filtering it would break the query.
    scoped = scope_sql("SELECT metric FROM semantic.metric_definitions", restricted)
    assert APPLE not in scoped


# --- the attacks -------------------------------------------------------------


def test_asking_for_a_forbidden_company_yields_a_filter_that_excludes_it(restricted):
    # The model writes a query for Microsoft. The rewrite leaves the model's own
    # predicate in place AND adds ours, so the intersection is empty.
    sql = f"SELECT revenue FROM marts.fct_company_annual WHERE cik = '{MSFT}'"
    scoped = scope_sql(sql, restricted)

    assert APPLE in scoped
    # Microsoft's own predicate survives, which is fine - it now ANDs against a
    # subquery that contains only Apple.
    assert "cik IN" in scoped.replace("\n", " ")


def test_a_principal_with_no_permitted_entities_sees_nothing(unrestricted):
    empty = AccessPolicy(principal=Principal(user_id="new", role=Role.ANALYST))
    scoped = scope_sql("SELECT cik FROM marts.dim_company", empty)
    # `IN ()` is a syntax error, so an empty scope must render as a
    # never-true predicate rather than as no predicate at all.
    assert "NULL" in scoped
    assert "cik IN" in scoped.replace("\n", " ")


def test_scoped_sql_still_passes_the_guard(restricted):
    """The two controls must compose, not fight."""
    scoped = scope_sql(
        "SELECT cik, revenue FROM marts.fct_company_annual WHERE fiscal_year = 2023",
        restricted,
    )
    result = validate(scoped)
    assert result.ok, result.errors


# --- retrieval scope ---------------------------------------------------------


def test_retrieval_scope_defaults_to_the_permitted_set(restricted):
    assert restricted.retrieval_ciks(None) == [APPLE]


def test_retrieval_scope_intersects_with_the_request(restricted):
    assert restricted.retrieval_ciks([APPLE, MSFT]) == [APPLE]


def test_retrieval_scope_of_a_forbidden_request_is_empty_not_absent(restricted):
    # An empty list must filter to nothing. Returning None here would widen the
    # search to the whole corpus, which is the exact leak being prevented.
    assert restricted.retrieval_ciks([MSFT]) == []


def test_unrestricted_retrieval_passes_the_request_through(unrestricted):
    assert unrestricted.retrieval_ciks(None) is None
    assert unrestricted.retrieval_ciks([MSFT]) == [MSFT]


def test_filter_ciks(restricted, unrestricted):
    assert restricted.filter_ciks([APPLE, MSFT]) == [APPLE]
    assert unrestricted.filter_ciks([APPLE, MSFT]) == [APPLE, MSFT]
