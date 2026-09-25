"""The question-answering endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sse_starlette.sse import EventSourceResponse

from finlens.agent.types import Answer
from finlens.api.auth import PrincipalDep
from finlens.api.deps import AgentDep
from finlens.api.schemas import (
    AskRequest,
    AskResponse,
    CitationOut,
    SqlOut,
    UsageOut,
    VerificationOut,
)
from finlens.logging import get_logger

log = get_logger(__name__)
router = APIRouter(tags=["ask"])


def to_response(answer: Answer, request: AskRequest) -> AskResponse:
    """Map the agent's answer onto the published contract."""
    sql: SqlOut | None = None
    if request.include_sql and answer.sql_result is not None:
        sql = SqlOut(
            sql=answer.sql_result.sql,
            generated_sql=answer.sql_result.generated_sql,
            explanation=answer.sql_result.explanation,
            columns=answer.sql_result.columns,
            rows=answer.sql_result.rows,
            row_count=answer.sql_result.row_count,
            truncated=answer.sql_result.truncated,
            error=answer.sql_result.error,
        )

    verification: VerificationOut | None = None
    if answer.verification is not None:
        report = answer.verification
        verification = VerificationOut(
            checked=report.checked,
            reconciled=report.reconciled,
            failed=report.failed,
            unchecked=report.unchecked,
            groundedness=report.groundedness,
            failures=[
                {
                    "text": v.claim.text,
                    "value": v.claim.value,
                    "verdict": v.verdict.value,
                    "detail": v.detail,
                }
                for v in report.failures()
            ],
        )

    return AskResponse(
        request_id=answer.request_id,
        question=answer.question,
        answer=answer.answer,
        route=answer.route,
        citations=[
            CitationOut(
                label=c.label,
                source_type=c.source_type,
                url=c.url,
                accession_number=c.accession_number,
                excerpt=c.excerpt if request.include_excerpts else None,
                score=c.score,
            )
            for c in answer.citations
        ],
        sql=sql,
        verification=verification,
        warnings=answer.warnings,
        reasoning=answer.reasoning,
        usage=UsageOut(
            input_tokens=answer.usage.input_tokens,
            output_tokens=answer.usage.output_tokens,
            cache_read_tokens=answer.usage.cache_read_tokens,
            calls=answer.usage.calls,
            provider=answer.usage.provider,
            model=answer.usage.model,
        ),
        elapsed_ms=round(answer.elapsed_ms, 1),
    )


@router.post("/ask", response_model=AskResponse, summary="Ask a question")
async def ask(request: AskRequest, agent: AgentDep, principal: PrincipalDep) -> AskResponse:
    """Answer a question about SEC filings, within the caller's entitlements.

    The agent is synchronous and does blocking I/O (DuckDB, the provider SDKs),
    so it runs in the threadpool rather than blocking the event loop. Making it
    async all the way down would buy nothing: the work is I/O against libraries
    with no async interface.
    """
    try:
        answer = await run_in_threadpool(
            agent.ask,
            request.question,
            principal=principal,
            force_route=request.route,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001
        log.error("api.ask_failed", error=str(exc), user=principal.user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to answer the question",
        ) from exc

    return to_response(answer, request)


@router.post("/ask/stream", summary="Ask a question, streaming progress and the answer")
async def ask_stream(
    request: AskRequest, agent: AgentDep, principal: PrincipalDep
) -> EventSourceResponse:
    """Server-sent events.

    Routing, query generation and retrieval all complete before any text can be
    produced, so the client gets progress events for those stages first. Without
    them the connection looks hung for several seconds on a hybrid question.
    """

    async def events():
        yield {"event": "status", "data": json.dumps({"stage": "routing"})}

        try:
            answer = await run_in_threadpool(
                agent.ask, request.question, principal=principal, force_route=request.route
            )
        except Exception as exc:  # noqa: BLE001
            log.error("api.stream_failed", error=str(exc))
            yield {"event": "error", "data": json.dumps({"error": str(exc)})}
            return

        yield {
            "event": "route",
            "data": json.dumps({"route": answer.route.value, "reasoning": answer.reasoning}),
        }

        if answer.sql_result is not None and answer.sql_result.ok:
            yield {
                "event": "sql",
                "data": json.dumps(
                    {"sql": answer.sql_result.sql, "row_count": answer.sql_result.row_count}
                ),
            }

        for citation in answer.citations:
            yield {
                "event": "citation",
                "data": json.dumps({"label": citation.label, "type": citation.source_type}),
            }

        if answer.verification is not None:
            yield {
                "event": "verification",
                "data": json.dumps(
                    {
                        "checked": answer.verification.checked,
                        "reconciled": answer.verification.reconciled,
                        "failed": answer.verification.failed,
                    }
                ),
            }

        # The answer is complete by this point - verification has to run over
        # the whole thing before any of it can be served. Chunking here keeps
        # the client contract identical to a token-level stream, so moving to
        # one later is not a breaking change.
        for paragraph in answer.answer.split("\n\n"):
            yield {"event": "token", "data": json.dumps({"text": paragraph + "\n\n"})}

        yield {
            "event": "done",
            "data": json.dumps(
                {
                    "request_id": answer.request_id,
                    "elapsed_ms": round(answer.elapsed_ms, 1),
                    "warnings": answer.warnings,
                    "tokens": answer.usage.total_tokens,
                }
            ),
        }

    return EventSourceResponse(events())
