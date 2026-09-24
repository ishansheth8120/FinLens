"""The SQL guard is a security control, so it is tested as one.

Both directions: legitimate analytical SQL must pass (a guard that blocks real
queries gets disabled), and everything outside the mart allowlist must fail.
"""

from __future__ import annotations

import pytest

from finlens.agent.sql_guard import SqlGuardError, referenced_tables, validate


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT cik FROM marts.dim_company",
        "SELECT * FROM marts.fct_company_annual WHERE fiscal_year = 2023",
        """
        WITH ranked AS (
            SELECT ticker, revenue,
                   row_number() OVER (ORDER BY revenue DESC) AS rn
            FROM marts.fct_company_annual
            WHERE fiscal_year = 2023
        )
        SELECT ticker, revenue FROM ranked WHERE rn <= 5
        """,
        """
        SELECT c.ticker, a.gross_margin
        FROM marts.fct_company_annual a
        JOIN marts.dim_company c ON c.cik = a.cik
        LEFT JOIN semantic.metric_definitions m ON TRUE
        """,
        "SELECT metric FROM semantic.metric_definitions",
    ],
)
def test_legitimate_analytical_sql_passes(sql):
    result = validate(sql)
    assert result.ok, result.errors


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE marts.dim_company",
        "DELETE FROM marts.dim_company",
        "INSERT INTO marts.dim_company VALUES ('1')",
        "UPDATE marts.dim_company SET cik = '1'",
        "CREATE TABLE evil AS SELECT 1",
        "ATTACH 'other.duckdb' AS other",
    ],
)
def test_writes_and_ddl_are_rejected(sql):
    result = validate(sql)
    assert not result.ok
    assert result.errors


def test_multiple_statements_are_rejected():
    result = validate("SELECT 1; DROP TABLE marts.dim_company")
    assert not result.ok
    assert any("one statement" in e for e in result.errors)


# --- the allowlist is the real control ---------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM staging.stg_facts",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM main.sqlite_master",
        "SELECT * FROM marts.dim_company JOIN staging.stg_facts USING (cik)",
    ],
)
def test_tables_outside_the_mart_allowlist_are_rejected(sql):
    result = validate(sql)
    assert not result.ok
    assert any("not permitted" in e for e in result.errors)


def test_a_cte_is_not_mistaken_for_a_table():
    # CTE names are local aliases. Treating them as tables would reject every
    # non-trivial query.
    sql = """
        WITH stg_facts AS (SELECT 1 AS x)
        SELECT x FROM stg_facts
    """
    assert validate(sql).ok


def test_unqualified_mart_names_are_allowed():
    assert validate("SELECT cik FROM dim_company").ok


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_parquet('s3://bucket/x.parquet')",
    ],
)
def test_filesystem_functions_are_rejected(sql):
    assert not validate(sql).ok


# --- parsing beats pattern matching ------------------------------------------


def test_a_keyword_inside_a_string_literal_is_not_a_keyword():
    # The regex-based version rejected this. Any company with an awkward name
    # would have been unanswerable.
    result = validate("SELECT cik FROM marts.dim_company WHERE company_name = 'Drop Inc.'")
    assert result.ok, result.errors


def test_a_keyword_inside_a_comment_is_not_a_keyword():
    assert validate("SELECT cik FROM marts.dim_company -- delete everything\n").ok


def test_a_column_named_like_a_keyword_is_allowed():
    assert validate("SELECT filing_date AS updated_at FROM marts.dim_filing").ok


def test_unparseable_sql_is_rejected_not_passed_through():
    result = validate("SELECT FROM WHERE ((( ")
    assert not result.ok


# --- bounding ----------------------------------------------------------------


def test_missing_limit_is_injected():
    result = validate("SELECT cik FROM marts.dim_company", row_limit=100)
    assert result.ok
    assert "LIMIT 100" in result.sql.upper()
    assert result.warnings


def test_an_oversized_limit_is_clamped():
    result = validate("SELECT cik FROM marts.dim_company LIMIT 999999", row_limit=100)
    assert result.ok
    assert "999999" not in result.sql
    assert "LIMIT 100" in result.sql.upper()


def test_an_acceptable_limit_is_preserved():
    result = validate("SELECT cik FROM marts.dim_company LIMIT 10", row_limit=1000)
    assert result.ok
    assert "LIMIT 10" in result.sql.upper()
    assert not result.warnings


def test_empty_query_is_rejected():
    assert not validate("").ok
    assert not validate("   ").ok


def test_raise_if_blocked():
    with pytest.raises(SqlGuardError):
        validate("DROP TABLE marts.dim_company").raise_if_blocked()
    assert validate("SELECT cik FROM marts.dim_company").raise_if_blocked()


# --- table extraction --------------------------------------------------------


def test_referenced_tables_covers_from_and_join():
    sql = """
        SELECT a.cik
        FROM marts.dim_company a
        JOIN marts.fct_company_annual b ON b.cik = a.cik
        LEFT JOIN semantic.metric_definitions m ON TRUE
    """
    assert referenced_tables(sql) == {
        "marts.dim_company",
        "marts.fct_company_annual",
        "semantic.metric_definitions",
    }


def test_referenced_tables_sees_through_subqueries():
    sql = """
        SELECT * FROM (
            SELECT cik FROM marts.fct_company_annual
        ) x JOIN marts.dim_company c USING (cik)
    """
    assert referenced_tables(sql) == {"marts.fct_company_annual", "marts.dim_company"}


def test_referenced_tables_is_empty_for_garbage():
    assert referenced_tables("!!! not sql !!!") == set()
