"""Column types shared across dialects.

``domain/intervals.py`` rejects any naive ``datetime`` with ``ValueError``
(see ADR: timestamps are always tz-aware in UTC). SQLite has no native
timezone-aware date/time type: it stores the value and, on read, returns
a naive ``datetime``. ``UTCDateTime`` closes that gap at the database
boundary so the domain never sees a naive one, on any dialect.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """``DateTime`` that normalizes to UTC on write and reassigns UTC on read."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                f"UTCDateTime requires a tz-aware datetime; received a naive one ({value!r})."
            )
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
