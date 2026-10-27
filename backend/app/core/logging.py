"""Structured logging configuration.

Every log record carries the request correlation ID (when one is active) so a single
business request can be traced across modules.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Attributes present on every LogRecord; anything else was passed via `extra=` and is emitted.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "color_message"}


class _CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_CorrelationFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s %(name)s [%(correlation_id)s] %(message)s"
            )
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Route uvicorn's own loggers through the same formatter. Its access log duplicates
    # the request log written by CorrelationIdMiddleware, so it is silenced.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
