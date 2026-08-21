"""Structured (JSON) logging -- stdlib only, no new dependency.

One JSON object per log line: ``timestamp``/``level``/``logger``/
``message``, plus any caller-supplied ``extra=`` fields not already part
of the standard ``LogRecord`` shape. API handlers deliberately avoid
tracebacks because database exceptions can embed bound payload values.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

__all__ = ["JsonFormatter", "configure_logging"]

_STANDARD_LOG_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


class JsonFormatter(logging.Formatter):
    """Renders each :class:`logging.LogRecord` as one JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_ATTRS:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Attaches one JSON-formatted ``StreamHandler`` to the root logger.

    Replaces any existing root handlers (e.g. a bare ``basicConfig``
    default) so every logger in the process -- including
    ``paro.api.errors``'s, via normal propagation -- emits structured
    output, with no per-module changes needed.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
