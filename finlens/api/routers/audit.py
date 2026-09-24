"""Audit and lineage endpoints.

`/audit/{request_id}` replays exactly what happened for one request: the
question, the route, the SQL the model wrote, the SQL that actually ran after
access scoping, the row count and result hash, the chunks retrieved, the answer,
and the numeric verification outcome.

`/lineage/{request_id}` walks the other direction — from the answer back through
the warehouse models and lake objects to the SEC filing URL.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from finlens.api.auth import AuditPrincipalDep
from finlens.governance.audit import AuditLog
from finlens.governance.lineage import trace

router = APIRouter(prefix="/audit", tags=["governance"])


def _log(request: Request) -> AuditLog:
    log: AuditLog | None = getattr(request.app.state, "audit", None)
    if log is None:  # pragma: no cover - only if lifespan did not run
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit log is not available",
        )
    return log


def _visible_to(record: dict[str, Any], principal) -> bool:
    """An analyst sees their own requests; an admin sees everyone's.

    Without this the audit log leaks other users' questions, which for a
    coverage-restricted deployment is itself sensitive - the questions reveal
    what other desks are looking at.
    """
    return principal.unrestricted or record.get("user_id") == principal.user_id


@router.get("", summary="Recent requests")
def recent(
    principal: AuditPrincipalDep,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    user_filter = None if principal.unrestricted else principal.user_id
    return _log(request).recent(limit=limit, user_id=user_filter)


@router.get("/stats", summary="Aggregate request statistics")
def stats(principal: AuditPrincipalDep, request: Request) -> dict[str, Any]:
    if not principal.unrestricted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="aggregate statistics are admin-only",
        )
    return _log(request).stats()


@router.get("/failures", summary="Requests with unreconciled figures")
def failures(
    principal: AuditPrincipalDep,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    """Answers where the numeric verifier caught something.

    The most useful view in the log: the list of answers the system would have
    served wrong if nothing had been checking them.
    """
    records = _log(request).failures(limit=limit)
    return [r for r in records if _visible_to(r, principal)]


@router.get("/{request_id}", summary="Replay one request")
def replay(request_id: str, principal: AuditPrincipalDep, request: Request) -> dict[str, Any]:
    record = _log(request).get(request_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no request {request_id}"
        )
    if not _visible_to(record, principal):
        # 404 rather than 403: confirming a request id exists is itself a leak.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no request {request_id}"
        )
    return record


@router.get("/{request_id}/lineage", summary="Trace a request back to SEC filings")
def lineage(request_id: str, principal: AuditPrincipalDep, request: Request) -> dict[str, Any]:
    record = _log(request).get(request_id)
    if record is None or not _visible_to(record, principal):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no request {request_id}"
        )

    trails = trace(
        tables=record.get("sql_tables") or [],
        citations=[{"chunk_id": c} for c in (record.get("chunk_ids") or [])],
    )
    return {
        "request_id": request_id,
        "question": record.get("question"),
        "answer": record.get("answer"),
        "trails": [t.to_dict() for t in trails],
        "rendered": "\n\n".join(t.render() for t in trails),
    }
