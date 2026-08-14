"""Motor determinista de OEE (Overall Equipment Effectiveness).

Formulas (formato Vorne/oee.com, documentadas en ``docs/oee-definition.md``)::

    Planned Production Time = duracion(ventana) - union(paros planeados ∩ ventana)
    Run Time                = Planned Production Time - union(paros no planeados ∩ ventana)

    Availability = Run Time / Planned Production Time
    Performance  = (Ideal Cycle Time x Total Count) / Run Time
    Quality      = Good Count / Total Count
    OEE          = Availability x Performance x Quality

Todo el modulo usa ``Decimal`` y segundos enteros: nunca ``float``. Un
denominador en cero nunca produce ``0.0`` ni una excepcion sin controlar;
produce ``None`` en ese componente y una advertencia nombrada en
``OeeResult.warnings`` (ver :mod:`paro.domain.warnings`). ``Performance`` por
encima de 100% se conserva crudo junto con una version limitada a 100% para
presentacion, nunca se recorta en silencio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from paro.domain.intervals import Interval, duration_seconds, subtract
from paro.domain.warnings import Warning

__all__ = ["DowntimeSpan", "OeeResult", "calculate_oee"]


@dataclass(frozen=True, slots=True)
class DowntimeSpan:
    """Un paro tal como llega del repositorio: puede seguir abierto.

    ``end is None`` representa un evento sin ``ended_at`` todavia. El motor lo
    cierra usando ``as_of`` (ver :func:`calculate_oee`) en vez de fallar, porque
    un turno en curso siempre tiene paros que todavia no terminan.
    """

    start: datetime
    end: datetime | None


@dataclass(frozen=True, slots=True)
class OeeResult:
    """Resultado del calculo, con componentes, duraciones y advertencias.

    Los componentes son ``Decimal | None``: ``None`` significa "no calculable
    con estos datos", nunca "cero". ``oee`` solo tiene valor cuando los tres
    componentes se pudieron calcular.
    """

    availability: Decimal | None
    performance_raw: Decimal | None
    performance_capped: Decimal | None
    quality: Decimal | None
    oee: Decimal | None
    planned_production_time_seconds: int
    run_time_seconds: int
    warnings: list[Warning] = field(default_factory=list)


def _resolve_span(span: DowntimeSpan, as_of: datetime) -> Interval | None:
    """Cierra un ``DowntimeSpan`` en un ``Interval``, usando ``as_of`` si esta abierto.

    Devuelve ``None`` cuando, tras resolver el fin, el intervalo queda vacio o
    invertido (por ejemplo un evento que abrio despues de ``as_of``): eso es un
    dato inusual, no un motivo para interrumpir el calculo de todo el reporte.
    """
    end = span.end if span.end is not None else as_of
    if end <= span.start:
        return None
    return Interval(span.start, end)


def _resolve_spans(spans: list[DowntimeSpan], as_of: datetime) -> tuple[list[Interval], bool]:
    intervals: list[Interval] = []
    any_open = False
    for span in spans:
        if span.end is None:
            any_open = True
        resolved = _resolve_span(span, as_of)
        if resolved is not None:
            intervals.append(resolved)
    return intervals, any_open


def _run_time_segments(
    planned_production_segments: list[Interval], unplanned_downtimes: list[Interval]
) -> list[Interval]:
    """Resta los paros no planeados de cada tramo de tiempo planeado.

    Se procesa tramo por tramo (en vez de tratar la ventana como un solo
    intervalo) porque los paros planeados ya pudieron haber partido la ventana
    en varios pedazos.
    """
    segments: list[Interval] = []
    for segment in planned_production_segments:
        segments.extend(subtract(segment, unplanned_downtimes))
    return segments


def calculate_oee(
    window: Interval,
    planned_downtimes: list[DowntimeSpan],
    unplanned_downtimes: list[DowntimeSpan],
    total_count: int,
    good_count: int,
    ideal_cycle_time_seconds: Decimal,
    as_of: datetime | None = None,
) -> OeeResult:
    """Calcula OEE para ``window`` a partir de paros y conteos de produccion.

    ``as_of`` cierra los eventos todavia abiertos; por defecto es el fin de
    ``window`` (documentado como la regla determinista para eventos abiertos).
    Los paros ya deben llegar separados en planeados/no planeados: esa
    clasificacion es un dato del evento, no algo que el motor de OEE decida.
    """
    if total_count < 0 or good_count < 0:
        raise ValueError("total_count y good_count no pueden ser negativos.")
    if good_count > total_count:
        raise ValueError(f"good_count ({good_count}) no puede superar total_count ({total_count}).")
    if ideal_cycle_time_seconds < 0:
        raise ValueError("ideal_cycle_time_seconds no puede ser negativo.")

    resolved_as_of = as_of if as_of is not None else window.end

    warnings_found: list[Warning] = []

    planned_intervals, planned_had_open = _resolve_spans(planned_downtimes, resolved_as_of)
    unplanned_intervals, unplanned_had_open = _resolve_spans(unplanned_downtimes, resolved_as_of)
    if planned_had_open or unplanned_had_open:
        warnings_found.append(Warning.OPEN_EVENT_CLIPPED)

    planned_production_segments = subtract(window, planned_intervals)
    planned_production_time_seconds = duration_seconds(planned_production_segments)

    run_time_segments = _run_time_segments(planned_production_segments, unplanned_intervals)
    run_time_seconds = duration_seconds(run_time_segments)

    availability: Decimal | None
    if planned_production_time_seconds == 0:
        availability = None
        warnings_found.append(Warning.ZERO_PLANNED_TIME)
    else:
        availability = Decimal(run_time_seconds) / Decimal(planned_production_time_seconds)

    performance_raw: Decimal | None
    performance_capped: Decimal | None
    if run_time_seconds == 0:
        performance_raw = None
        performance_capped = None
        warnings_found.append(Warning.ZERO_RUN_TIME)
    else:
        performance_raw = (ideal_cycle_time_seconds * total_count) / Decimal(run_time_seconds)
        if performance_raw > 1:
            performance_capped = Decimal(1)
            warnings_found.append(Warning.PERFORMANCE_OVER_100)
        else:
            performance_capped = performance_raw

    quality: Decimal | None
    if total_count == 0:
        quality = None
        warnings_found.append(Warning.ZERO_TOTAL_COUNT)
    else:
        quality = Decimal(good_count) / Decimal(total_count)

    oee: Decimal | None = None
    if availability is not None and performance_raw is not None and quality is not None:
        oee = availability * performance_raw * quality

    return OeeResult(
        availability=availability,
        performance_raw=performance_raw,
        performance_capped=performance_capped,
        quality=quality,
        oee=oee,
        planned_production_time_seconds=planned_production_time_seconds,
        run_time_seconds=run_time_seconds,
        warnings=warnings_found,
    )
