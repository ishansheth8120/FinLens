"""Request and response models for the HTTP API.

Separate from `finlens.agent.types` on purpose. The agent's types are free to
change shape as the pipeline evolves; these are a published contract. Where they
happen to coincide today, the mapping in `routers/ask.py` is what keeps a change
to one from silently breaking the other.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from finlens.agent.types import Route

MAX_QUESTION_CHARS = 2000


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    route: Route | None = Field(
        default=None, description="Force a route. Omit to let the router decide."
    )
    include_sql: bool = Field(default=True, description="Return the generated SQL and rows")
    include_excerpts: bool = Field(default=True, description="Return retrieved text excerpts")

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("question cannot be blank")
        return stripped


class CitationOut(BaseModel):
    label: str
    source_type: str
    url: str | None = None
    accession_number: str | None = None
    excerpt: str | None = None
    score: float | None = None


class SqlOut(BaseModel):
    sql: str
    generated_sql: str | None = Field(
        default=None,
        description="What the model wrote before access scoping. Compare with `sql`.",
    )
    explanation: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    error: str | None = None


class UsageOut(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    calls: int = 0
    provider: str | None = None
    model: str | None = None


class VerificationOut(BaseModel):
    """Result of reconciling every asserted figure against the query rows."""

    checked: int = 0
    reconciled: int = 0
    failed: int = 0
    unchecked: int = 0
    groundedness: float | None = Field(
        default=None, description="reconciled / checked; null when nothing was checkable"
    )
    failures: list[dict[str, Any]] = Field(default_factory=list)


class AskResponse(BaseModel):
    request_id: str | None = Field(
        default=None, description="Look this up at /audit/{request_id}"
    )
    question: str
    answer: str
    route: Route
    citations: list[CitationOut] = Field(default_factory=list)
    sql: SqlOut | None = None
    verification: VerificationOut | None = None
    warnings: list[str] = Field(default_factory=list)
    reasoning: str | None = None
    usage: UsageOut = Field(default_factory=UsageOut)
    elapsed_ms: float = 0.0


class CompanyOut(BaseModel):
    cik: str
    ticker: str | None = None
    company_name: str
    exchange: str | None = None
    sector: str | None = None
    filing_count: int = 0
    latest_filing_date: str | None = None
    has_financial_data: bool = False


class FilingOut(BaseModel):
    accession_number: str
    cik: str
    ticker: str | None = None
    form: str
    filing_date: str | None = None
    filing_url: str | None = None
    is_indexed: bool = False


class MetricOut(BaseModel):
    metric: str
    description: str | None = None
    unit: str | None = None
    period_type: str | None = None
    companies_reporting: int = 0
    first_year: int | None = None
    latest_year: int | None = None


class HealthOut(BaseModel):
    status: str
    version: str
    warehouse_available: bool
    index_available: bool
    llm_configured: bool
    embedding_provider: str
    detail: list[str] = Field(default_factory=list)


class ErrorOut(BaseModel):
    error: str
    detail: str | None = None
