"""Logging setup shared by the CLIs, the API and the Airflow tasks.

Console-friendly by default, JSON when ``FINLENS_LOG_JSON=true`` so the same
code produces parseable output inside a container without a second code path.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_configured = False


def configure_logging(level: str | None = None, json_output: bool | None = None) -> None:
    """Idempotently configure stdlib logging and structlog.

    Safe to call from every entrypoint; only the first call takes effect, so an
    Airflow task that imports two of our modules does not get doubled handlers.
    """
    global _configured
    if _configured:
        return

    from finlens.config import get_settings

    settings = get_settings()
    resolved_level = (level or settings.log_level).upper()
    resolved_json = settings.log_json if json_output is None else json_output

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, resolved_level, logging.INFO),
    )
    # httpx logs every request at INFO; at our EDGAR request volume that buries
    # everything else.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if resolved_json
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, resolved_level, logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.get_logger(name)
