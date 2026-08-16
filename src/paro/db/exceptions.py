"""Domain exceptions for the persistence layer.

They are not ``HTTPException``: the API (Sprint 3) translates them to
status codes. Keeping them here, instead of in ``paro.api``, keeps
``paro.db`` from depending on FastAPI and gives the caller enough
information to build a useful 409 without re-querying the row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

__all__ = ["DuplicateWithDifferentPayloadError", "StaleUpdateError"]


class DuplicateWithDifferentPayloadError(Exception):
    """The idempotency key (``source``, ``external_id``) already exists with different data.

    Raised when an idempotent insert finds an existing row with the same
    key but whose business fields differ from the incoming payload (see
    ``paro.db.repositories``). Different from a plain duplicate: that case
    is a silent no-op, not an exception.
    """

    def __init__(
        self,
        *,
        entity: str,
        source: str,
        external_id: str,
        differing_fields: dict[str, tuple[Any, Any]],
    ) -> None:
        self.entity = entity
        self.source = source
        self.external_id = external_id
        self.differing_fields = differing_fields
        fields = ", ".join(sorted(differing_fields))
        super().__init__(
            f"{entity}: source={source!r} external_id={external_id!r} already exists with "
            f"different data in: {fields}"
        )


class StaleUpdateError(Exception):
    """A PATCH's ``expected_updated_at`` no longer matches the row's current value.

    Optimistic-concurrency conflict: someone else updated the row between
    the caller reading it and submitting this PATCH. Carries both
    timestamps so the caller can decide whether to re-fetch and retry
    without a second round trip.
    """

    def __init__(
        self,
        *,
        entity: str,
        id: int,
        expected_updated_at: datetime,
        actual_updated_at: datetime,
    ) -> None:
        self.entity = entity
        self.id = id
        self.expected_updated_at = expected_updated_at
        self.actual_updated_at = actual_updated_at
        super().__init__(
            f"{entity} id={id}: expected_updated_at={expected_updated_at!r} does not match "
            f"the current updated_at={actual_updated_at!r}"
        )
