"""JSON-safe serialization shared across layers that must not depend on FastAPI.

``paro.db`` doesn't depend on ``paro.api`` (see ``db/exceptions.py``), so
this lives at the package root rather than under ``api/`` -- both
``api/errors.py`` (409 bodies) and ``db/repositories.py`` (audit-log diffs)
import it from here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

__all__ = ["json_safe"]


def json_safe(value: Any) -> Any:
    """Converts a value to something JSON-serializable without going through ``float``.

    ``Decimal`` is serialized as a string and ``datetime`` as ISO 8601: the
    same rule Pydantic responses follow, so downstream consumers never lose
    precision or let a naive datetime slip through by accident.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value
