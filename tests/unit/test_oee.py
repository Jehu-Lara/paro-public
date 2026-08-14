"""Pruebas del motor de OEE.

Cada caso documenta el calculo manual esperado en un comentario. Los conteos y
tiempos se eligen para que las fracciones resultantes sean decimales exactos
(denominadores con solo factores 2 y 5), asi ``Decimal`` no tiene que redondear
y los valores esperados se pueden escribir como literales legibles.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from paro.domain.intervals import Interval
from paro.domain.oee import DowntimeSpan, calculate_oee
from paro.domain.warnings import Warning


def at(hour: int, minute: int = 0) -> datetime:
    """Atajo para un datetime UTC del 2026-01-01."""
    return datetime(2026, 1, 1, hour, minute, tzinfo=UTC)


WINDOW = Interval(at(6), at(14))  # turno de 8h = 28800s


def test_happy_path_without_downtime() -> None:
    """Sin paros: PPT = Run Time = 8h. Performance y Quality se eligen exactos.

    PPT = Run Time = 28800s -> Availability = 1
    Performance = (30s x 480) / 28800s = 14400 / 28800 = 0.5
    Quality = 456 / 480 = 0.95
    OEE = 1 x 0.5 x 0.95 = 0.475
    """
    result = calculate_oee(
        window=WINDOW,
        planned_downtimes=[],
        unplanned_downtimes=[],
        total_count=480,
        good_count=456,
        ideal_cycle_time_seconds=Decimal(30),
    )

    assert result.planned_production_time_seconds == 28800
    assert result.run_time_seconds == 28800
    assert result.availability == Decimal(1)
    assert result.performance_raw == Decimal("0.5")
    assert result.performance_capped == Decimal("0.5")
    assert result.quality == Decimal("0.95")
    assert result.oee == Decimal("0.475")
    assert result.warnings == []


def test_planned_downtime_is_removed_from_planned_production_time() -> None:
    """Un paro planeado (comida, 30 min) reduce el PPT, no el Run Time.

    PPT = 28800 - 1800 = 27000s. Sin paros no planeados, Run Time = PPT.
    Performance = (27s x 500) / 27000 = 13500 / 27000 = 0.5
    Quality = 475 / 500 = 0.95
    Availability = 27000 / 27000 = 1
    OEE = 1 x 0.5 x 0.95 = 0.475
    """
    lunch = DowntimeSpan(start=at(10), end=at(10, 30))

    result = calculate_oee(
        window=WINDOW,
        planned_downtimes=[lunch],
        unplanned_downtimes=[],
        total_count=500,
        good_count=475,
        ideal_cycle_time_seconds=Decimal(27),
    )

    assert result.planned_production_time_seconds == 27000
    assert result.run_time_seconds == 27000
    assert result.availability == Decimal(1)
    assert result.performance_raw == Decimal("0.5")
    assert result.quality == Decimal("0.95")
    assert result.oee == Decimal("0.475")
    assert result.warnings == []


def test_unplanned_downtime_reduces_run_time_but_not_planned_production_time() -> None:
    """Un paro no planeado (2h) reduce el Run Time; el PPT no cambia.

    PPT = 28800s (sin paros planeados).
    Run Time = 28800 - 7200 = 21600s.
    Availability = 21600 / 28800 = 0.75
    Performance = (27s x 480) / 21600 = 12960 / 21600 = 0.6
    Quality = 432 / 480 = 0.9
    OEE = 0.75 x 0.6 x 0.9 = 0.405
    """
    machine_fault = DowntimeSpan(start=at(8), end=at(10))

    result = calculate_oee(
        window=WINDOW,
        planned_downtimes=[],
        unplanned_downtimes=[machine_fault],
        total_count=480,
        good_count=432,
        ideal_cycle_time_seconds=Decimal(27),
    )

    assert result.planned_production_time_seconds == 28800
    assert result.run_time_seconds == 21600
    assert result.availability == Decimal("0.75")
    assert result.performance_raw == Decimal("0.6")
    assert result.quality == Decimal("0.9")
    assert result.oee == Decimal("0.405")
    assert result.warnings == []


def test_overlapping_unplanned_downtimes_are_not_double_counted() -> None:
    """Dos paros no planeados que se solapan 30 min no deben restarse dos veces.

    Paro A: 08:00-09:00 (1h). Paro B: 08:30-09:30 (1h). Union = 08:00-09:30 = 5400s.
    Si se contaran por separado (sin unir) se restarian 7200s en vez de 5400s.

    PPT = 28800s. Run Time = 28800 - 5400 = 23400s.
    Availability = 23400 / 28800 = 0.8125 (13/16, decimal exacto)
    Performance = (39s x 300) / 23400 = 11700 / 23400 = 0.5
    Quality = 270 / 300 = 0.9
    OEE = 0.8125 x 0.5 x 0.9 = 0.365625
    """
    fault_a = DowntimeSpan(start=at(8), end=at(9))
    fault_b = DowntimeSpan(start=at(8, 30), end=at(9, 30))

    result = calculate_oee(
        window=WINDOW,
        planned_downtimes=[],
        unplanned_downtimes=[fault_a, fault_b],
        total_count=300,
        good_count=270,
        ideal_cycle_time_seconds=Decimal(39),
    )

    assert result.run_time_seconds == 23400  # no 21600 (28800 - 7200)
    assert result.availability == Decimal("0.8125")
    assert result.performance_raw == Decimal("0.5")
    assert result.oee == Decimal("0.365625")
    assert result.warnings == []


def test_open_event_is_clipped_using_window_end_as_default_as_of() -> None:
    """Un evento sin `ended_at` se cierra con `as_of` (por defecto, fin de ventana).

    Evento abierto desde 13:30, sin `as_of` explicito -> se cierra en las 14:00
    (fin de `window`), duracion 1800s.

    PPT = 28800s. Run Time = 28800 - 1800 = 27000s.
    Availability = 27000 / 28800 = 0.9375 (15/16, decimal exacto)
    Performance = (45s x 300) / 27000 = 13500 / 27000 = 0.5
    Quality = 270 / 300 = 0.9
    OEE = 0.9375 x 0.5 x 0.9 = 0.421875
    """
    still_running = DowntimeSpan(start=at(13, 30), end=None)

    result = calculate_oee(
        window=WINDOW,
        planned_downtimes=[],
        unplanned_downtimes=[still_running],
        total_count=300,
        good_count=270,
        ideal_cycle_time_seconds=Decimal(45),
    )

    assert result.run_time_seconds == 27000
    assert result.availability == Decimal("0.9375")
    assert result.oee == Decimal("0.421875")
    assert Warning.OPEN_EVENT_CLIPPED in result.warnings


def test_explicit_as_of_closes_open_event_before_window_end() -> None:
    """Con `as_of` explicito, el evento abierto se cierra ahi, no al fin de ventana."""
    still_running = DowntimeSpan(start=at(13), end=None)

    result = calculate_oee(
        window=WINDOW,
        planned_downtimes=[],
        unplanned_downtimes=[still_running],
        total_count=100,
        good_count=100,
        ideal_cycle_time_seconds=Decimal(1),
        as_of=at(13, 20),
    )

    assert result.run_time_seconds == 28800 - 1200  # 13:00-13:20 = 20 min
    assert Warning.OPEN_EVENT_CLIPPED in result.warnings


def test_performance_over_100_percent_keeps_raw_value_and_adds_capped_with_warning() -> None:
    """Ideal Cycle Time mal configurado produce Performance > 100%.

    Sin paros: PPT = Run Time = 28800s.
    Performance crudo = (40s x 900) / 28800 = 36000 / 28800 = 1.25 (125%)
    Quality = 810 / 900 = 0.9
    OEE se calcula con el valor CRUDO (no se recorta en silencio):
    OEE = 1 x 1.25 x 0.9 = 1.125
    """
    result = calculate_oee(
        window=WINDOW,
        planned_downtimes=[],
        unplanned_downtimes=[],
        total_count=900,
        good_count=810,
        ideal_cycle_time_seconds=Decimal(40),
    )

    assert result.planned_production_time_seconds == 28800
    assert result.availability == Decimal(1)
    assert result.performance_raw == Decimal("1.25")
    assert result.performance_capped == Decimal(1)
    assert result.oee == Decimal("1.125")
    assert Warning.PERFORMANCE_OVER_100 in result.warnings


def test_zero_total_count_quality_is_none_with_warning() -> None:
    """Sin produccion registrada, Quality no es calculable: None, no 0.0.

    PPT = Run Time = 28800s -> Availability = 1 (si es calculable).
    Performance = (30s x 0) / 28800 = 0 (si es calculable, es un cero legitimo,
    no un caso de denominador cero).
    """
    result = calculate_oee(
        window=WINDOW,
        planned_downtimes=[],
        unplanned_downtimes=[],
        total_count=0,
        good_count=0,
        ideal_cycle_time_seconds=Decimal(30),
    )

    assert result.quality is None
    assert result.performance_raw == Decimal(0)
    assert result.availability == Decimal(1)
    assert result.oee is None  # no se puede calcular sin Quality
    assert Warning.ZERO_TOTAL_COUNT in result.warnings


def test_zero_planned_production_time_cascades_to_availability_and_performance() -> None:
    """Un paro planeado que cubre toda la ventana deja PPT = 0.

    Sin tiempo de produccion planeado tampoco hay tiempo operativo posible:
    Run Time tambien es 0. Ambos componentes quedan en None con su warning.
    Quality si se puede calcular porque no depende del tiempo.
    """
    entire_window_planned = DowntimeSpan(start=at(6), end=at(14))

    result = calculate_oee(
        window=WINDOW,
        planned_downtimes=[entire_window_planned],
        unplanned_downtimes=[],
        total_count=100,
        good_count=90,
        ideal_cycle_time_seconds=Decimal(10),
    )

    assert result.planned_production_time_seconds == 0
    assert result.run_time_seconds == 0
    assert result.availability is None
    assert result.performance_raw is None
    assert result.performance_capped is None
    assert result.quality == Decimal("0.9")
    assert result.oee is None
    assert Warning.ZERO_PLANNED_TIME in result.warnings
    assert Warning.ZERO_RUN_TIME in result.warnings


def test_zero_run_time_performance_is_none_even_when_ppt_is_positive() -> None:
    """Un paro no planeado que cubre todo el PPT deja Run Time = 0 con PPT > 0."""
    downtime_covers_everything = DowntimeSpan(start=at(6), end=at(14))

    result = calculate_oee(
        window=WINDOW,
        planned_downtimes=[],
        unplanned_downtimes=[downtime_covers_everything],
        total_count=100,
        good_count=90,
        ideal_cycle_time_seconds=Decimal(10),
    )

    assert result.planned_production_time_seconds == 28800
    assert result.run_time_seconds == 0
    assert result.availability == Decimal(0)
    assert result.performance_raw is None
    assert result.oee is None
    assert Warning.ZERO_RUN_TIME in result.warnings
    assert Warning.ZERO_PLANNED_TIME not in result.warnings


def test_degenerate_span_with_end_before_or_equal_start_is_ignored_not_raised() -> None:
    """Un span con fin <= inicio (dato inconsistente) se ignora, no rompe el calculo."""
    degenerate = DowntimeSpan(start=at(9), end=at(9))  # duracion cero
    real_downtime = DowntimeSpan(start=at(10), end=at(10, 30))

    result = calculate_oee(
        window=WINDOW,
        planned_downtimes=[],
        unplanned_downtimes=[degenerate, real_downtime],
        total_count=10,
        good_count=10,
        ideal_cycle_time_seconds=Decimal(1),
    )

    assert result.run_time_seconds == 28800 - 1800


def test_negative_total_count_raises_value_error() -> None:
    with pytest.raises(ValueError, match="no pueden ser negativos"):
        calculate_oee(
            window=WINDOW,
            planned_downtimes=[],
            unplanned_downtimes=[],
            total_count=-1,
            good_count=0,
            ideal_cycle_time_seconds=Decimal(1),
        )


def test_negative_good_count_raises_value_error() -> None:
    with pytest.raises(ValueError, match="no pueden ser negativos"):
        calculate_oee(
            window=WINDOW,
            planned_downtimes=[],
            unplanned_downtimes=[],
            total_count=10,
            good_count=-1,
            ideal_cycle_time_seconds=Decimal(1),
        )


def test_good_count_greater_than_total_count_raises_value_error() -> None:
    with pytest.raises(ValueError, match="no puede superar"):
        calculate_oee(
            window=WINDOW,
            planned_downtimes=[],
            unplanned_downtimes=[],
            total_count=10,
            good_count=11,
            ideal_cycle_time_seconds=Decimal(1),
        )


def test_negative_ideal_cycle_time_raises_value_error() -> None:
    with pytest.raises(ValueError, match="ideal_cycle_time_seconds"):
        calculate_oee(
            window=WINDOW,
            planned_downtimes=[],
            unplanned_downtimes=[],
            total_count=10,
            good_count=10,
            ideal_cycle_time_seconds=Decimal(-1),
        )
