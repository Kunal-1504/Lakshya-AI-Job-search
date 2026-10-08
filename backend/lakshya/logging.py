"""Structured JSON logging with recursive credential redaction and request context."""

import logging
import os
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import structlog

SENSITIVE = {
    "api_key",
    "anthropic_api_key",
    "gemini_api_key",
    "x-goog-api-key",
    "adzuna_app_key",
    "adzuna_app_id",
    "password",
    "authorization",
    "x-api-key",
    "access_token",
    "refresh_token",
    "credentials",
    "database_url",
}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key).lower() in SENSITIVE else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        for name in (
            "LAKSHYA_API_KEY",
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "ADZUNA_APP_ID",
            "ADZUNA_APP_KEY",
            "LAKSHYA_DATABASE_URL",
        ):
            secret = os.getenv(name)
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value


def redact_event(logger: Any, method_name: str, event: MutableMapping[str, Any]) -> dict[str, Any]:
    return dict(redact(event))


def configure_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        format="%(message)s",
        level=os.getenv("LAKSHYA_LOG_LEVEL", "INFO"),
        handlers=[logging.StreamHandler(), logging.FileHandler(path, encoding="utf-8")],
        force=True,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_event,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    for name in ("httpx", "httpcore", "sqlalchemy.engine", "weasyprint", "fontTools"):
        logging.getLogger(name).setLevel(logging.WARNING)
