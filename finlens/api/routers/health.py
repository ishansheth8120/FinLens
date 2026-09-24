"""Health and readiness.

`/health` is liveness: the process is up. `/ready` is readiness: it can actually
answer a question. They are separate because a container whose warehouse has not
been built yet is alive and should not receive traffic, and conflating the two
makes a deploy either flap or serve errors.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Response, status

from finlens import __version__
from finlens.api.deps import SettingsDep
from finlens.api.schemas import HealthOut

router = APIRouter(tags=["health"])


def _probe(settings: SettingsDep) -> HealthOut:
    warehouse = Path(settings.duckdb_path).exists()
    index = (Path(settings.vector_store_path) / "chunks.duckdb").exists()
    # The SDK also resolves ANTHROPIC_AUTH_TOKEN and an `ant auth login`
    # profile, so an unset API key is not proof of no credentials - this is a
    # hint for operators, not a hard gate.
    llm = bool(
        settings.anthropic_api_key
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )

    detail: list[str] = []
    if not warehouse:
        detail.append(f"no warehouse at {settings.duckdb_path}")
    if not index:
        detail.append(f"no vector index at {settings.vector_store_path}")
    if not llm:
        detail.append("no Anthropic credential found in the environment")
    if settings.embedding_provider == "hash":
        detail.append("embedding provider is the non-semantic `hash` stand-in")

    return HealthOut(
        status="ok" if (warehouse or index) else "degraded",
        version=__version__,
        warehouse_available=warehouse,
        index_available=index,
        llm_configured=llm,
        embedding_provider=settings.embedding_provider,
        detail=detail,
    )


@router.get("/health", response_model=HealthOut, summary="Liveness")
def health(settings: SettingsDep) -> HealthOut:
    """Always 200 while the process is serving."""
    return _probe(settings)


@router.get("/ready", response_model=HealthOut, summary="Readiness")
def ready(settings: SettingsDep, response: Response) -> HealthOut:
    """503 unless at least one store is available to answer from."""
    probe = _probe(settings)
    if not (probe.warehouse_available or probe.index_available):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return probe
