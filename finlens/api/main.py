"""FastAPI application.

Startup builds the expensive shared handles once; shutdown closes them. Nothing
here is aware of how an answer is produced.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from finlens import __version__
from finlens.agent.orchestrator import Agent
from finlens.api.routers import ask, audit, auth, catalog, health, ui
from finlens.config import get_settings
from finlens.logging import configure_logging, get_logger

log = get_logger(__name__)

DESCRIPTION = """
Question answering over SEC EDGAR filings.

Numeric questions are answered from a dbt warehouse of normalised XBRL facts;
narrative questions from a vector index over filing text. A router decides
which, and every answer carries citations back to the filing it came from.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    settings.ensure_dirs()

    app.state.agent = Agent(settings)
    app.state.audit = app.state.agent.audit

    # The warehouse may legitimately not exist yet on a fresh deployment. The
    # browse endpoints then return 503 with an actionable message rather than
    # the whole service failing to start.
    if Path(settings.duckdb_path).exists():
        app.state.executor = app.state.agent.executor
    else:
        app.state.executor = None
        log.warning("api.no_warehouse", path=str(settings.duckdb_path))

    log.info(
        "api.started",
        version=__version__,
        warehouse=str(settings.duckdb_path),
        embedding_provider=settings.embedding_provider,
    )
    try:
        yield
    finally:
        app.state.agent.close()
        log.info("api.stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title="FinLens",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def timing(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
        log.info(
            "api.request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            elapsed_ms=round(elapsed_ms, 1),
        )
        return response

    @application.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        # Most ValueErrors here come from identifier normalisation, which is a
        # client mistake rather than a server fault.
        return JSONResponse(status_code=400, content={"error": "bad request", "detail": str(exc)})

    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(ask.router)
    application.include_router(catalog.router)
    application.include_router(audit.router)
    application.include_router(ui.router)

    return application


app = create_app()


def main() -> None:
    """`python -m finlens.api.main` - dev server."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "finlens.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )


if __name__ == "__main__":
    main()
