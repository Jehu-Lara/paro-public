"""Algebra de intervalos de tiempo para el calculo de paros.

Todos los intervalos son **medio-abiertos**: ``[start, end)``. Esa eleccion no es
cosmetica; es lo que hace que dos turnos consecutivos (06:00-14:00 y 14:00-22:00)
particionen el dia sin solapamiento ni hueco, y que un evento que termina justo
cuando otro empieza no comparta ni un segundo con el.

Reglas del modulo:

* Todos los ``datetime`` deben ser *tz-aware*. Un ``datetime`` naive es un error
  de programacion, no un valor por defecto: se rechaza con ``ValueError``.
* Un intervalo vacio o invertido (``end <= start``) no existe: se rechaza.
* Las operaciones son puras y deterministas. Ninguna funcion consulta el reloj.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

__all__ = ["Interval", "clip", "duration_seconds", "subtract", "total_seconds", "union"]


def _require_aware(moment: datetime, field: str) -> datetime:
    """Valida que ``moment`` sea tz-aware y lo normaliza a UTC."""
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(
            f"{field} debe ser un datetime tz-aware; se recibio uno naive ({moment!r}). "
            "PARO almacena y calcula siempre en UTC."
        )
    return moment.astimezone(UTC)


@dataclass(frozen=True, slots=True, order=True)
class Interval:
    """Intervalo de tiempo medio-abierto ``[start, end)`` en UTC.

    Es inmutable y ordenable por ``start`` (y luego por ``end``), lo que permite
    ordenar listas de intervalos sin escribir una clave de ordenamiento.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start = _require_aware(self.start, "start")
        end = _require_aware(self.end, "end")
        if end <= start:
            raise ValueError(
                f"Un intervalo requiere end > start; se recibio start={start.isoformat()} "
                f"end={end.isoformat()}."
            )
        # El dataclass es frozen: para normalizar a UTC hay que saltarse el setattr.
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    @property
    def seconds(self) -> int:
        """Duracion en segundos enteros.

        Se usan segundos enteros (no ``float``) para que las sumas de duraciones
        sean exactas y el calculo de OEE pueda hacerse con ``Decimal``.
        """
        return int((self.end - self.start).total_seconds())


def clip(interval: Interval, window: Interval) -> Interval | None:
    """Recorta ``interval`` a ``window``.

    Devuelve ``None`` cuando no hay interseccion, en lugar de un intervalo vacio:
    un intervalo de duracion cero no existe en este modelo, y devolver ``None``
    obliga a quien llama a tratar el caso de forma explicita.

    Es la operacion que hace que un paro que cruza el limite de turno aporte a
    cada turno solamente su porcion.
    """
    start = max(interval.start, window.start)
    end = min(interval.end, window.end)
    if end <= start:
        return None
    return Interval(start, end)


def union(intervals: list[Interval]) -> list[Interval]:
    """Fusiona intervalos solapados **y adyacentes** en una lista disjunta.

    Es la pieza que evita el doble conteo: si dos paros se solapan, los segundos
    compartidos aparecen una sola vez en el resultado.

    Los adyacentes se fusionan a proposito: dos paros consecutivos sin hueco
    (14:00-14:05 y 14:05-14:10) son diez minutos de linea detenida de forma
    continua, y contarlos como un solo tramo es lo correcto para disponibilidad.

    Devuelve una lista nueva ordenada por ``start``; no muta la entrada.
    """
    if not intervals:
        return []

    merged: list[Interval] = []
    for current in sorted(intervals):
        if merged and current.start <= merged[-1].end:
            last = merged[-1]
            if current.end > last.end:
                merged[-1] = Interval(last.start, current.end)
            # Si current esta contenido en last, no aporta nada.
        else:
            merged.append(current)
    return merged


def subtract(base: Interval, to_remove: list[Interval]) -> list[Interval]:
    """Resta ``to_remove`` de ``base`` y devuelve los tramos que quedan.

    Aplica ``union`` internamente, asi que acepta listas con solapamientos sin
    restar dos veces los mismos segundos. Si ``to_remove`` cubre todo ``base``,
    devuelve una lista vacia.
    """
    remaining: list[Interval] = []
    cursor = base.start

    for block in union(to_remove):
        clipped = clip(block, base)
        if clipped is None:
            continue
        if clipped.start > cursor:
            remaining.append(Interval(cursor, clipped.start))
        cursor = max(cursor, clipped.end)

    if cursor < base.end:
        remaining.append(Interval(cursor, base.end))
    return remaining


def duration_seconds(intervals: list[Interval]) -> int:
    """Segundos cubiertos por ``intervals``, contando los solapes una sola vez."""
    return sum(item.seconds for item in union(intervals))


def total_seconds(intervals: list[Interval]) -> int:
    """Suma cruda de duraciones, **sin** deduplicar solapes.

    Existe para poder medir cuanto tiempo se reasigno por solapamiento
    (``total_seconds - duration_seconds``) y reportarlo como advertencia de
    calidad de datos. No debe usarse para calcular disponibilidad.
    """
    return sum(item.seconds for item in intervals)
