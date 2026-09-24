"""Shared dependencies.

The `Agent` and the `SqlExecutor` hold open DuckDB handles and a pooled HTTP
client, so they are built once at startup and injected, not constructed per
request. Rebuilding them per request roughly triples latency on a short question
and opens a new file handle each time.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from finlens.agent.executor import SqlExecutor
from finlens.agent.orchestrator import Agent
from finlens.config import Settings, get_settings


def get_app_settings() -> Settings:
    return get_settings()


def get_agent(request: Request) -> Agent:
    agent: Agent | None = getattr(request.app.state, "agent", None)
    if agent is None:  # pragma: no cover - only if lifespan did not run
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="agent is not initialised",
        )
    return agent


def get_executor(request: Request) -> SqlExecutor:
    """Read-only warehouse access for the browse endpoints.

    Raises 503 rather than 500 when the warehouse is missing: it is a
    deployment state the caller can act on, not a bug.
    """
    executor: SqlExecutor | None = getattr(request.app.state, "executor", None)
    if executor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="warehouse is not available - run `make warehouse`",
        )
    return executor


def query_rows(executor: SqlExecutor, sql: str) -> list[dict[str, Any]]:
    """Run a read query and return dicts, or raise a clean HTTP error."""
    result = executor.execute(sql)
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"warehouse query failed: {result.error}",
        )
    return [dict(zip(result.columns, row)) for row in result.rows]


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
AgentDep = Annotated[Agent, Depends(get_agent)]
ExecutorDep = Annotated[SqlExecutor, Depends(get_executor)]
