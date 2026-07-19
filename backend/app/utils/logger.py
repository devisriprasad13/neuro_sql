"""
Structured JSON logger for NeuroSQL.

Every log entry is a JSON object. This makes logs machine-readable
and compatible with log aggregation tools like Datadog, CloudWatch,
and the ELK stack.

Usage:
    from app.utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("query_executed", user_id=str(user_id), latency_ms=142)
"""

import logging
import sys
from typing import Any

import structlog
from app.config import get_settings

settings = get_settings()


def _configure_stdlib_logging() -> None:
    """
    Configure Python's standard logging to route through structlog.
    This ensures that third-party libraries (SQLAlchemy, httpx, etc.)
    also emit structured logs instead of plain text.
    """
    log_level = logging.DEBUG if settings.is_development else logging.INFO

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )


def _build_processors(is_development: bool) -> list:
    """
    Build the structlog processor chain.

    Processors transform log entries sequentially.
    In development: pretty-printed colored output for readability.
    In production: compact JSON for machine consumption.
    """
    shared_processors = [
        # Add log level (INFO, WARNING, ERROR) to every entry
        structlog.stdlib.add_log_level,
        # Add timestamp in ISO-8601 format
        structlog.processors.TimeStamper(fmt="iso"),
        # Add the logger name (module path) to every entry
        # Format exception info into the log entry
        structlog.processors.format_exc_info,
        # Render stack info if present
        structlog.processors.StackInfoRenderer(),
    ]

    if is_development:
        # Human-readable colored output for local development
        return shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        # Machine-readable JSON for production
        return shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]


def configure_logging() -> None:
    """
    Initialize the logging system.
    Call this once at application startup in main.py.
    """
    _configure_stdlib_logging()

    structlog.configure(
        processors=_build_processors(settings.is_development),
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.is_development else logging.INFO
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """
    Get a named structured logger.

    Args:
        name: Typically __name__ of the calling module.

    Returns:
        A structlog BoundLogger instance.

    Example:
        logger = get_logger(__name__)
        logger.info("schema_crawled", connection_id=str(conn_id), table_count=42)
    """
    return structlog.get_logger(name)