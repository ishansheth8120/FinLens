"""Types passed between agent stages.

Pydantic throughout, because several of these are also the schemas the model
fills in via structured outputs, and the same definition serving as both the
API contract and the model contract keeps them from drifting apart.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Route(str, Enum):
    """Where a question should be answered from."""

    SQL = "sql"
    """Numeric, comparative or aggregate. Answered from the warehouse."""

    RAG = "rag"
    """Narrative, qualitative or explanatory. Answered from filing text."""

    HYBRID = "hybrid"
    """Needs both - a figure plus the explanation the filing gives for it."""

    METADATA = "metadata"
    """About coverage itself: which companies, which years, what is indexed."""

    REFUSE = "refuse"
    """Out of scope, or asking for something the corpus cannot support -
    forward-looking predictions, investment advice, non-EDGAR data."""


class Entities(BaseModel):
    """What the router extracted from the question.

    Doubles as the retrieval filter, so a wrong extraction here narrows the
    search to nothing rather than merely mis-scoring it.
    """

    tickers: list[str] = Field(default_factory=list)
    company_names: list[str] = Field(default_factory=list)
    ciks: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list, description="Names from `metric_definitions`")
    fiscal_years: list[int] = Field(default_factory=list)
    forms: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list, description="Filing item numbers, e.g. `1A`")


class RouteDecision(BaseModel):
    """The router's output. Also the structured-output schema it fills in."""

    route: Route
    reasoning: str = Field(description="One or two sentences on why this route")
    entities: Entities = Field(default_factory=Entities)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    refusal_reason: str | None = None


class GeneratedSql(BaseModel):
    """A candidate query plus the model's account of it."""

    sql: str
    explanation: str = Field(description="What the query computes, in one sentence")
    tables_used: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(
        default_factory=list,
        description="Anything the query had to decide that the question left open",
    )


class SqlResult(BaseModel):
    """Outcome of executing a generated query."""

    sql: str
    generated_sql: str | None = Field(
        default=None,
        description="What the model wrote, before access scoping. The diff "
        "against `sql` is the access control, and the audit log keeps both.",
    )
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    elapsed_ms: float = 0.0
    error: str | None = None
    explanation: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_markdown(self, max_rows: int = 25) -> str:
        """Render for inclusion in a synthesis prompt."""
        if self.error:
            return f"Query failed: {self.error}"
        if not self.rows:
            return "Query returned no rows."

        shown = self.rows[:max_rows]
        header = " | ".join(self.columns)
        divider = " | ".join("---" for _ in self.columns)
        body = "\n".join(" | ".join(_format_cell(c) for c in row) for row in shown)
        footer = (
            f"\n\n({len(self.rows)} rows, showing {len(shown)})" if len(self.rows) > max_rows else ""
        )
        return f"{header}\n{divider}\n{body}{footer}"


def _format_cell(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        # Keep small ratios readable without destroying large dollar figures.
        return f"{value:,.4f}" if abs(value) < 1000 else f"{value:,.0f}"
    return str(value)


class Citation(BaseModel):
    """A pointer back to the source. Every claim in an answer needs one."""

    label: str
    source_type: str = Field(description="`filing` or `warehouse`")
    chunk_id: str | None = None
    section_id: str | None = None
    accession_number: str | None = None
    url: str | None = None
    excerpt: str | None = None
    score: float | None = None


class RetrievalResult(BaseModel):
    query: str
    citations: list[Citation] = Field(default_factory=list)
    contexts: list[str] = Field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def is_empty(self) -> bool:
        return not self.contexts


class Usage(BaseModel):
    """Token accounting, aggregated across every model call in one answer."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0
    # Which provider actually served the call. Worth recording because the
    # fallback chain means it is not always the one that was configured, and an
    # eval run served half by Groq is not comparable to one served by Gemini.
    provider: str | None = None
    model: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            calls=self.calls + other.calls,
            provider=other.provider or self.provider,
            model=other.model or self.model,
        )


class NumericClaim(BaseModel):
    """A number the model asserted, and where it says the number came from.

    The model is required to emit one of these for every figure in its
    commentary. That requirement is what makes the claim checkable: a bare
    sentence containing "15.2%" cannot be reconciled against anything, but a
    claim carrying its value, its unit and the rows it came from can.
    """

    text: str = Field(description="The clause containing the figure, quoted from the commentary")
    value: float = Field(description="The figure itself, as a number")
    unit: str | None = Field(default=None, description="USD, percent, ratio, shares, ...")
    source_rows: list[int] = Field(
        default_factory=list,
        description="Indices into the SQL result rows the figure was taken or derived from",
    )
    derivation: str | None = Field(
        default=None,
        description="If computed rather than read directly, the arithmetic performed",
    )


class ClaimVerdict(str, Enum):
    RECONCILED = "reconciled"
    """The figure matches a value present in, or derivable from, the rows."""

    MISMATCH = "mismatch"
    """A number was found for this claim, and it is not the one asserted."""

    UNSUPPORTED = "unsupported"
    """No value in the result set corresponds to the figure at all."""

    UNCHECKABLE = "uncheckable"
    """No structured result to check against - a pure-RAG answer, for example."""


class ClaimVerification(BaseModel):
    """The verifier's finding for one numeric claim."""

    claim: NumericClaim
    verdict: ClaimVerdict
    matched_value: float | None = None
    relative_error: float | None = None
    detail: str = ""

    @property
    def is_failure(self) -> bool:
        return self.verdict in (ClaimVerdict.MISMATCH, ClaimVerdict.UNSUPPORTED)


class VerificationReport(BaseModel):
    """Whole-answer numeric verification.

    `groundedness` is the headline number in the eval: the share of asserted
    figures that reconcile against the warehouse rows they claim to come from.
    """

    verifications: list[ClaimVerification] = Field(default_factory=list)
    checked: int = 0
    reconciled: int = 0
    failed: int = 0
    unchecked: int = 0

    @property
    def groundedness(self) -> float | None:
        """Reconciled / checkable. ``None`` when there was nothing to check."""
        return self.reconciled / self.checked if self.checked else None

    @property
    def has_failures(self) -> bool:
        return self.failed > 0

    def failures(self) -> list[ClaimVerification]:
        return [v for v in self.verifications if v.is_failure]


class SynthesisOutput(BaseModel):
    """The structured shape synthesis must return.

    Prose alone would be unverifiable. Splitting the answer into commentary plus
    an explicit list of numeric claims and citations is what lets the verifier
    run at all, and what lets the API redact an individual unreconciled sentence
    instead of discarding the whole answer.
    """

    commentary: str = Field(description="The answer, in prose, with [n] citation markers")
    numeric_claims: list[NumericClaim] = Field(default_factory=list)
    citation_indices: list[int] = Field(
        default_factory=list, description="1-based indices of the excerpts actually used"
    )
    caveats: list[str] = Field(default_factory=list)


class Answer(BaseModel):
    """What the agent returns, and what the API serialises."""

    question: str
    answer: str
    route: Route
    citations: list[Citation] = Field(default_factory=list)
    numeric_claims: list[NumericClaim] = Field(default_factory=list)
    verification: VerificationReport | None = None
    sql_result: SqlResult | None = None
    retrieval: RetrievalResult | None = None
    reasoning: str | None = None
    warnings: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    elapsed_ms: float = 0.0
    request_id: str | None = None
