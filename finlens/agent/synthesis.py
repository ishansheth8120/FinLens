"""Composing the answer, then checking it.

The order matters and is the whole design: the model writes commentary *plus* a
structured list of the figures it asserted, and the verifier reconciles every
one of those against the query rows before the answer is returned. A figure that
does not reconcile is stripped out, not annotated.

Two guards sit either side of the model call:

* **Before** — if there is no usable evidence, the model is not called at all.
  Given an empty evidence block and a question about Apple, a model will answer
  from what it knows about Apple. Fluent, plausible, and entirely outside the
  audit trail this system exists to provide.
* **After** — `finlens.agent.verifier` reconciles the numbers.
"""

from __future__ import annotations

from finlens.agent.llm import LlmClient, LlmError, get_llm
from finlens.agent.prompts import load_prompt
from finlens.agent.types import (
    Answer,
    Citation,
    RetrievalResult,
    Route,
    SqlResult,
    SynthesisOutput,
)
from finlens.agent.verifier import redact_failures, verify
from finlens.config import Settings, get_settings
from finlens.logging import get_logger

log = get_logger(__name__)

# Rows shown to the model. Beyond this the prompt bloats and the model starts
# summarising the table instead of answering the question; the verifier still
# reconciles against the full result set.
MAX_PROMPT_ROWS = 40


def build_evidence(
    sql_result: SqlResult | None,
    retrieval: RetrievalResult | None,
) -> str:
    """Assemble the evidence block.

    Rows are numbered so `numeric_claims.source_rows` can point at them, and
    excerpts are numbered so `[n]` citations resolve.
    """
    blocks: list[str] = []

    if sql_result is not None:
        if sql_result.ok:
            blocks.append(
                "<warehouse_result>\n"
                f"Query intent: {sql_result.explanation or 'n/a'}\n\n"
                f"```sql\n{sql_result.sql}\n```\n\n"
                f"{_numbered_rows(sql_result)}\n"
                "</warehouse_result>"
            )
        else:
            # The failure is evidence too: it tells synthesis to explain rather
            # than to guess.
            blocks.append(
                f"<warehouse_result>\nThe query could not be completed: "
                f"{sql_result.error}\n</warehouse_result>"
            )

    if retrieval is not None and retrieval.contexts:
        blocks.append("<filing_excerpts>\n" + "\n\n".join(retrieval.contexts) + "\n</filing_excerpts>")

    return "\n\n".join(blocks)


def _numbered_rows(result: SqlResult) -> str:
    """Result rows as a markdown table with an explicit row index column."""
    if not result.rows:
        return "Query returned no rows."

    shown = result.rows[:MAX_PROMPT_ROWS]
    header = " | ".join(["row", *result.columns])
    divider = " | ".join(["---"] * (len(result.columns) + 1))
    body = "\n".join(
        " | ".join([str(i), *(_cell(c) for c in row)]) for i, row in enumerate(shown)
    )
    footer = (
        f"\n\n({result.row_count} rows total, showing the first {len(shown)})"
        if result.row_count > len(shown)
        else ""
    )
    return f"{header}\n{divider}\n{body}{footer}"


def _cell(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:,.6g}"
    return str(value)


def has_usable_evidence(sql_result: SqlResult | None, retrieval: RetrievalResult | None) -> bool:
    if sql_result is not None and sql_result.ok and sql_result.rows:
        return True
    return retrieval is not None and bool(retrieval.contexts)


def _no_evidence_answer(
    sql_result: SqlResult | None, retrieval: RetrievalResult | None
) -> str:
    """A deterministic answer for the empty-evidence case.

    Written in code, not generated. The one thing that must never happen here is
    a model filling the gap from memory.
    """
    if sql_result is not None and not sql_result.ok:
        return (
            f"I could not answer this from the warehouse. The query failed: {sql_result.error}\n\n"
            "That usually means the metric or company requested is not in the warehouse. "
            "Ask what coverage is available if you are not sure what is indexed."
        )
    if sql_result is not None and sql_result.ok and not sql_result.rows:
        return (
            "The warehouse has no rows matching this question. That means the company, "
            "metric or period is not covered — not that the value is zero."
        )
    if retrieval is not None and retrieval.is_empty:
        return (
            "No filing text matching this question is in the index. The text corpus covers "
            "a deliberately narrow set of companies and years; anything outside it has "
            "nothing to search."
        )
    return (
        "I do not have evidence to answer this. Neither the warehouse nor the filing "
        "index addresses the question as asked."
    )


def _select_citations(
    output: SynthesisOutput, retrieval: RetrievalResult | None, sql_result: SqlResult | None
) -> list[Citation]:
    """Keep only the citations the model actually used.

    Returning all twenty retrieved chunks as "sources" would make citation
    precision meaningless - the answer would cite everything and therefore
    nothing.
    """
    citations: list[Citation] = []

    if retrieval is not None and retrieval.citations:
        used = set(output.citation_indices)
        for index, citation in enumerate(retrieval.citations, start=1):
            if not used or index in used:
                citations.append(citation)

    if sql_result is not None and sql_result.ok and sql_result.rows:
        citations.append(
            Citation(
                label=f"FinLens warehouse ({sql_result.row_count} rows)",
                source_type="warehouse",
                excerpt=sql_result.sql,
            )
        )
    return citations


def synthesize(
    question: str,
    *,
    route: Route,
    sql_result: SqlResult | None = None,
    retrieval: RetrievalResult | None = None,
    reasoning: str | None = None,
    warnings: list[str] | None = None,
    llm: LlmClient | None = None,
    settings: Settings | None = None,
    redact_unverified: bool = True,
) -> Answer:
    """Turn evidence into a cited, numerically verified answer."""
    settings = settings or get_settings()
    warnings = list(warnings or [])

    if not has_usable_evidence(sql_result, retrieval):
        log.info("synthesis.no_evidence", route=route.value)
        return Answer(
            question=question,
            answer=_no_evidence_answer(sql_result, retrieval),
            route=route,
            citations=_select_citations(SynthesisOutput(commentary=""), None, sql_result),
            sql_result=sql_result,
            retrieval=retrieval,
            reasoning=reasoning,
            warnings=warnings,
        )

    llm = llm or get_llm(settings)
    prompt = f"<question>\n{question}\n</question>\n\n{build_evidence(sql_result, retrieval)}"

    try:
        output, usage = llm.parse(
            prompt,
            system=load_prompt("synthesis"),
            schema=SynthesisOutput,
            max_tokens=settings.llm_max_tokens,
        )
    except LlmError as exc:
        log.error("synthesis.failed", error=str(exc))
        warnings.append(f"answer generation failed: {exc}")
        # Degrade to the raw evidence rather than to nothing. Someone looking at
        # the query result still gets their answer; they just have to read it.
        fallback = (
            _numbered_rows(sql_result)
            if sql_result is not None and sql_result.ok
            else "Retrieved excerpts are attached as citations."
        )
        return Answer(
            question=question,
            answer=f"Could not generate a written answer. Raw evidence:\n\n{fallback}",
            route=route,
            citations=_select_citations(SynthesisOutput(commentary=""), retrieval, sql_result),
            sql_result=sql_result,
            retrieval=retrieval,
            reasoning=reasoning,
            warnings=warnings,
        )

    # --- verification --------------------------------------------------------
    report = verify(output.numeric_claims, sql_result)
    commentary = output.commentary

    if redact_unverified and report.has_failures:
        commentary, redaction_warnings = redact_failures(commentary, report)
        warnings.extend(redaction_warnings)

    warnings.extend(output.caveats)
    if sql_result is not None and sql_result.truncated:
        warnings.append(
            f"Results were truncated at {sql_result.row_count} rows; the answer may not "
            "reflect the full set."
        )

    log.info(
        "synthesis.done",
        route=route.value,
        claims=len(output.numeric_claims),
        reconciled=report.reconciled,
        failed=report.failed,
    )

    return Answer(
        question=question,
        answer=commentary.strip(),
        route=route,
        citations=_select_citations(output, retrieval, sql_result),
        numeric_claims=output.numeric_claims,
        verification=report,
        sql_result=sql_result,
        retrieval=retrieval,
        reasoning=reasoning,
        warnings=warnings,
        usage=usage,
    )
