"""Browse endpoints: companies, filings, metrics.

These exist so a client can populate a picker or check coverage without going
through the LLM. Every query here is written by hand, parameterised, and run on
the same read-only connection - none of it touches the text-to-SQL path.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from finlens.api.deps import ExecutorDep, query_rows
from finlens.api.schemas import CompanyOut, FilingOut, MetricOut
from finlens.identifiers import normalize_cik

router = APIRouter(tags=["catalog"])


def _escape(value: str) -> str:
    """Escape a single-quoted SQL literal.

    Used only for the handful of literals below, all of which are already length-
    and character-constrained by the route signature. The read-only connection
    is the real boundary; this keeps a quote in a company name from breaking the
    query.
    """
    return value.replace("'", "''")


@router.get("/companies", response_model=list[CompanyOut], summary="Search companies")
def list_companies(
    executor: ExecutorDep,
    q: Annotated[str | None, Query(max_length=100, description="Name or ticker substring")] = None,
    sector: Annotated[str | None, Query(max_length=60)] = None,
    with_financials: Annotated[bool, Query(description="Only companies with XBRL data")] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[CompanyOut]:
    predicates = ["TRUE"]
    if q:
        term = _escape(q.strip())
        predicates.append(f"(company_name ILIKE '%{term}%' OR ticker ILIKE '{term}%')")
    if sector:
        predicates.append(f"sector = '{_escape(sector)}'")
    if with_financials:
        predicates.append("has_financial_data")

    rows = query_rows(
        executor,
        f"""
        SELECT cik, ticker, company_name, exchange, sector,
               filing_count, cast(latest_filing_date AS VARCHAR) AS latest_filing_date,
               has_financial_data
        FROM marts.dim_company
        WHERE {' AND '.join(predicates)}
        ORDER BY filing_count DESC, company_name
        LIMIT {limit}
        """,
    )
    return [CompanyOut(**row) for row in rows]


@router.get("/companies/{cik}", response_model=CompanyOut, summary="One company")
def get_company(cik: str, executor: ExecutorDep) -> CompanyOut:
    try:
        normalized = normalize_cik(cik)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid CIK: {cik}"
        ) from exc

    rows = query_rows(
        executor,
        f"""
        SELECT cik, ticker, company_name, exchange, sector,
               filing_count, cast(latest_filing_date AS VARCHAR) AS latest_filing_date,
               has_financial_data
        FROM marts.dim_company
        WHERE cik = '{normalized}'
        """,
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no company {cik}")
    return CompanyOut(**rows[0])


@router.get("/companies/{cik}/filings", response_model=list[FilingOut], summary="A company's filings")
def list_filings(
    cik: str,
    executor: ExecutorDep,
    form: Annotated[str | None, Query(max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[FilingOut]:
    try:
        normalized = normalize_cik(cik)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid CIK: {cik}"
        ) from exc

    predicates = [f"cik = '{normalized}'"]
    if form:
        predicates.append(f"base_form = '{_escape(form.upper())}'")

    rows = query_rows(
        executor,
        f"""
        SELECT accession_number, cik, ticker, form,
               cast(filing_date AS VARCHAR) AS filing_date, filing_url, is_indexed
        FROM marts.dim_filing
        WHERE {' AND '.join(predicates)}
        ORDER BY filing_date DESC
        LIMIT {limit}
        """,
    )
    return [FilingOut(**row) for row in rows]


@router.get("/metrics", response_model=list[MetricOut], summary="Available metrics")
def list_metrics(executor: ExecutorDep) -> list[MetricOut]:
    """What the warehouse can answer numerically, and how well it is covered."""
    rows = query_rows(
        executor,
        """
        SELECT metric, description, unit, period_type,
               companies_reporting, first_year, latest_year
        FROM semantic.metric_definitions
        ORDER BY companies_reporting DESC
        """,
    )
    return [MetricOut(**row) for row in rows]
