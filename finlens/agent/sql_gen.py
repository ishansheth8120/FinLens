"""Text-to-SQL with a bounded repair loop.

Generation is one structured call. Execution can still fail — a mistyped column,
a metric name that does not exist, a DuckDB function that does not — and those
failures are informative: the error message names the problem precisely. So a
failed query is fed back with its error for one or two repair attempts before
giving up.

The loop is capped at two repairs deliberately. Measured on the eval set, the
first repair recovers most recoverable failures and the second a few more; past
that the model tends to rewrite the query into something that runs but answers a
different question, which is worse than an honest failure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from finlens.agent.executor import SqlExecutor
from finlens.agent.llm import LlmClient, LlmError, get_llm
from finlens.agent.prompts import render
from finlens.agent.schema_catalog import get_catalog_text, metric_names
from finlens.agent.sql_guard import referenced_tables
from finlens.agent.types import Entities, GeneratedSql, SqlResult, Usage
from finlens.config import Settings, get_settings
from finlens.logging import get_logger

log = get_logger(__name__)

MAX_REPAIRS = 2


@dataclass
class SqlAttempt:
    sql: str
    error: str | None
    explanation: str


def build_system_prompt(settings: Settings | None = None) -> str:
    """The text-to-SQL system prompt.

    Byte-stable for a given warehouse build, which is what lets it sit behind
    the prompt-cache breakpoint - it is by far the largest thing in the request.
    """
    settings = settings or get_settings()
    return render(
        "sql_gen",
        catalog=get_catalog_text(),
        metrics=", ".join(metric_names(settings)) or "(warehouse not built)",
    )


def _user_prompt(question: str, entities: Entities | None) -> str:
    parts = [f"<question>\n{question}\n</question>"]

    if entities:
        hints: list[str] = []
        if entities.tickers:
            hints.append(f"tickers: {', '.join(entities.tickers)}")
        if entities.company_names:
            hints.append(f"companies: {', '.join(entities.company_names)}")
        if entities.metrics:
            hints.append(f"metrics: {', '.join(entities.metrics)}")
        if entities.fiscal_years:
            hints.append(f"years: {', '.join(str(y) for y in entities.fiscal_years)}")
        if hints:
            parts.append(
                "<extracted_entities>\n"
                + "\n".join(hints)
                + "\n</extracted_entities>\n"
                "These were extracted from the question and may be incomplete or wrong. "
                "Prefer the question itself where they disagree."
            )

    return "\n\n".join(parts)


def _repair_prompt(question: str, attempts: list[SqlAttempt]) -> str:
    history = "\n\n".join(
        f"<attempt n=\"{i + 1}\">\n<sql>\n{a.sql}\n</sql>\n<error>{a.error}</error>\n</attempt>"
        for i, a in enumerate(attempts)
    )
    return (
        f"<question>\n{question}\n</question>\n\n"
        f"{history}\n\n"
        "The query above failed. Write a corrected query that answers the original question. "
        "Fix the specific error reported - do not restructure the query or change what it "
        "computes unless the error requires it."
    )


def generate_sql(
    question: str,
    *,
    entities: Entities | None = None,
    llm: LlmClient | None = None,
    settings: Settings | None = None,
) -> tuple[GeneratedSql, Usage]:
    """One generation attempt, with no execution."""
    settings = settings or get_settings()
    llm = llm or get_llm(settings)
    return llm.parse(
        _user_prompt(question, entities),
        system=build_system_prompt(settings),
        schema=GeneratedSql,
        max_tokens=4000,
    )


def answer_with_sql(
    question: str,
    *,
    entities: Entities | None = None,
    llm: LlmClient | None = None,
    executor: SqlExecutor | None = None,
    settings: Settings | None = None,
    max_repairs: int = MAX_REPAIRS,
    scope: Callable[[str], str] | None = None,
) -> tuple[SqlResult, Usage]:
    """Generate, scope, execute, and repair on failure.

    ``scope`` rewrites the query to the caller's access scope before it runs.
    Applied *after* generation and *before* execution, so the model never sees
    the filter and a repair attempt cannot strip it - each repair re-scopes.

    Returns the last result whether or not it succeeded; a failed `SqlResult`
    carries its error so synthesis can tell the user what went wrong instead of
    inventing an answer.
    """
    settings = settings or get_settings()
    llm = llm or get_llm(settings)
    owns_executor = executor is None
    executor = executor or SqlExecutor(settings)
    total = Usage()
    attempts: list[SqlAttempt] = []

    try:
        system = build_system_prompt(settings)

        for attempt_number in range(max_repairs + 1):
            prompt = (
                _user_prompt(question, entities)
                if not attempts
                else _repair_prompt(question, attempts)
            )

            try:
                generated, usage = llm.parse(
                    prompt, system=system, schema=GeneratedSql, max_tokens=4000
                )
            except LlmError as exc:
                log.error("sql_gen.model_failed", error=str(exc))
                return SqlResult(sql="", error=f"could not generate SQL: {exc}"), total

            total = total.add(usage)

            to_run = scope(generated.sql) if scope else generated.sql
            result = executor.execute(to_run, explanation=generated.explanation)
            # Keep what the model wrote alongside what ran: the difference is
            # the access control, and the audit log shows both.
            result.generated_sql = generated.sql

            if result.ok:
                log.info(
                    "sql_gen.succeeded",
                    attempt=attempt_number + 1,
                    rows=result.row_count,
                    tables=sorted(referenced_tables(result.sql)),
                )
                return result, total

            log.warning(
                "sql_gen.failed", attempt=attempt_number + 1, error=result.error
            )
            attempts.append(
                SqlAttempt(
                    sql=generated.sql, error=result.error, explanation=generated.explanation
                )
            )

        # Exhausted the repair budget. Return the last failure with its history
        # so the caller can explain what was tried.
        return (
            SqlResult(
                sql=attempts[-1].sql,
                generated_sql=attempts[-1].sql,
                error=f"{attempts[-1].error} (failed after {len(attempts)} attempts)",
                explanation=attempts[-1].explanation,
            ),
            total,
        )
    finally:
        if owns_executor:
            executor.close()
