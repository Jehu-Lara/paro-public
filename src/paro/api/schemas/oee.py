"""Schema de salida para ``GET /oee``.

El shape refleja exactamente ``paro.domain.oee.OeeResult`` (mismos campos,
sin resumir ni renombrar) mas metadatos de la consulta (``line_id``,
``window_start``, ``window_end``). Los ``Decimal`` se serializan como string
para que no exista ambiguedad sobre si pasaron por ``float`` en algun punto.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_serializer

from paro.domain.warnings import Warning

__all__ = ["OEEResponse"]

_DECIMAL_FIELDS = (
    "availability",
    "performance_raw",
    "performance_capped",
    "quality",
    "oee",
)


class OEEResponse(BaseModel):
    """Resultado de OEE para una linea y ventana de tiempo dadas."""

    line_id: int
    window_start: datetime
    window_end: datetime

    availability: Decimal | None
    performance_raw: Decimal | None
    performance_capped: Decimal | None
    quality: Decimal | None
    oee: Decimal | None
    planned_production_time_seconds: int
    run_time_seconds: int
    warnings: list[Warning]

    @field_serializer(*_DECIMAL_FIELDS)
    def _serialize_decimal(self, value: Decimal | None) -> str | None:
        """Serializa como string: nunca pasa por ``float``, precision exacta."""
        return None if value is None else str(value)
