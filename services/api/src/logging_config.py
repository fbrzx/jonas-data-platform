"""Structured logging configuration using structlog.

Call configure_logging() once at application startup (in main.py lifespan).
After that, all modules use:

    import structlog
    logger = structlog.get_logger(__name__)
    logger.info("event", key="value")

In development (LOG_FORMAT=text) output is coloured and human-readable.
In production (LOG_FORMAT=json, the default) output is newline-delimited JSON,
ready for ingestion by Datadog / Loki / CloudWatch / etc.
"""

import logging
import logging.config
import os

import structlog


def configure_logging() -> None:
    """Wire structlog and stdlib logging together."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "json").lower()  # "json" | "text"

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if log_format == "text":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)

    # Quieten noisy third-party loggers
    for name in ("uvicorn.access", "apscheduler"):
        logging.getLogger(name).setLevel(logging.WARNING)
