"""Pruebas del algebra de intervalos.

Todos los timestamps se pasan explicitamente; ningun test depende de
``datetime.now()`` ni de la hora en la que se ejecuta.
"""

from datetime import UTC, datetime, timedelta, timezone, tzinfo

import pytest

from paro.domain.intervals import Interval, clip, duration_seconds, subtract, total_seconds, union


def at(hour: int, minute: int = 0, day: int = 1) -> datetime:
    """Atajo para construir un datetime UTC del 2026-01-{day}."""
    return datetime(2026, 1, day, hour, minute, tzinfo=UTC)


# --- Interval: construccion y validacion -----------------------------------


def test_interval_rejects_naive_datetime() -> None:
    naive = datetime(2026, 1, 1, 8, 0)  # sin tzinfo
    with pytest.raises(ValueError, match="tz-aware"):
        Interval(naive, at(9))


class _BrokenTzinfo(tzinfo):
    """``tzinfo`` that is not ``None`` but whose ``utcoffset()`` is.

    Reproduces the case ``tzinfo is None`` doesn't cover: a tz-like object
    present but unable to resolve a real offset.
    """

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "broken"


def test_interval_rejects_tzinfo_with_none_utcoffset() -> None:
    broken = datetime(2026, 1, 1, 8, 0, tzinfo=_BrokenTzinfo())
    with pytest.raises(ValueError, match="tz-aware"):
        Interval(broken, at(9))


def test_interval_rejects_end_before_or_equal_start() -> None:
    with pytest.raises(ValueError, match="end > start"):
        Interval(at(9), at(8))
    with pytest.raises(ValueError, match="end > start"):
        Interval(at(9), at(9))


def test_interval_normalizes_non_utc_timezone_to_utc() -> None:
    minus_six = timezone(timedelta(hours=-6))
    local_start = datetime(2026, 1, 1, 2, 0, tzinfo=minus_six)  # == 08:00 UTC
    interval = Interval(local_start, at(9))

    assert interval.start == at(8)


def test_interval_seconds() -> None:
    assert Interval(at(8), at(9)).seconds == 3600


# --- clip --------------------------------------------------------------


def test_clip_partial_overlap_returns_intersection() -> None:
    event = Interval(at(7), at(9))
    window = Interval(at(8), at(16))

    assert clip(event, window) == Interval(at(8), at(9))


def test_clip_no_overlap_returns_none() -> None:
    event = Interval(at(5), at(6))
    window = Interval(at(8), at(16))

    assert clip(event, window) is None


def test_clip_adjacent_interval_returns_none() -> None:
    """El extremo derecho es abierto: tocar el borde no cuenta como solape."""
    event = Interval(at(6), at(8))
    window = Interval(at(8), at(16))

    assert clip(event, window) is None


def test_clip_event_fully_inside_window_is_unchanged() -> None:
    event = Interval(at(9), at(10))
    window = Interval(at(8), at(16))

    assert clip(event, window) == event


# --- union ---------------------------------------------------------------


def test_union_empty_list_returns_empty() -> None:
    assert union([]) == []


def test_union_single_interval_is_unchanged() -> None:
    interval = Interval(at(8), at(9))
    assert union([interval]) == [interval]


def test_union_two_overlapping_intervals_merge_into_one() -> None:
    a = Interval(at(8), at(10))
    b = Interval(at(9), at(11))

    assert union([a, b]) == [Interval(at(8), at(11))]


def test_union_adjacent_intervals_merge_into_one() -> None:
    """Fin de A == inicio de B: se fusionan (paro continuo sin hueco)."""
    a = Interval(at(8), at(9))
    b = Interval(at(9), at(10))

    assert union([a, b]) == [Interval(at(8), at(10))]


def test_union_disjoint_intervals_stay_separate_and_sorted() -> None:
    a = Interval(at(10), at(11))
    b = Interval(at(8), at(9))

    assert union([a, b]) == [Interval(at(8), at(9)), Interval(at(10), at(11))]


def test_union_three_chained_overlapping_intervals_merge_into_one() -> None:
    a = Interval(at(8), at(10))
    b = Interval(at(9, 30), at(11))
    c = Interval(at(10, 45), at(12))

    assert union([a, b, c]) == [Interval(at(8), at(12))]


def test_union_interval_fully_contained_in_another_is_absorbed() -> None:
    outer = Interval(at(8), at(12))
    inner = Interval(at(9), at(10))

    assert union([outer, inner]) == [Interval(at(8), at(12))]


def test_union_does_not_mutate_input_list() -> None:
    intervals = [Interval(at(9), at(10)), Interval(at(8), at(9))]
    original = list(intervals)

    union(intervals)

    assert intervals == original


# --- subtract --------------------------------------------------------------


def test_subtract_removing_entire_window_leaves_empty_list() -> None:
    base = Interval(at(6), at(14))
    remove = [Interval(at(6), at(14))]

    assert subtract(base, remove) == []


def test_subtract_interval_starting_before_and_ending_after_base_leaves_empty() -> None:
    base = Interval(at(8), at(10))
    remove = [Interval(at(6), at(12))]

    assert subtract(base, remove) == []


def test_subtract_middle_chunk_leaves_two_remaining_intervals() -> None:
    base = Interval(at(6), at(14))
    remove = [Interval(at(9), at(10))]

    assert subtract(base, remove) == [Interval(at(6), at(9)), Interval(at(10), at(14))]


def test_subtract_nothing_to_remove_returns_base_unchanged() -> None:
    base = Interval(at(6), at(14))

    assert subtract(base, []) == [base]


def test_subtract_overlapping_removals_do_not_double_subtract() -> None:
    """Dos paros solapados no deben restar mas tiempo del que realmente cubren."""
    base = Interval(at(6), at(14))
    remove = [Interval(at(8), at(10)), Interval(at(9), at(11))]

    assert subtract(base, remove) == [Interval(at(6), at(8)), Interval(at(11), at(14))]


def test_subtract_removal_outside_base_is_ignored() -> None:
    base = Interval(at(8), at(10))
    remove = [Interval(at(11), at(12))]

    assert subtract(base, remove) == [base]


def test_subtract_event_crossing_shift_boundary_only_contributes_its_slice() -> None:
    """Un paro que cruza el limite de turno solo debe afectar la ventana dada."""
    morning_shift = Interval(at(6), at(14))
    crossing_event = Interval(at(13), at(15))  # sigue tras el fin del turno

    remaining = subtract(morning_shift, [crossing_event])

    assert remaining == [Interval(at(6), at(13))]
    clipped_to_shift = clip(crossing_event, morning_shift)
    assert clipped_to_shift == Interval(at(13), at(14))
    assert clipped_to_shift.seconds == 3600


# --- duration_seconds / total_seconds --------------------------------------


def test_duration_seconds_of_overlapping_intervals_counts_shared_time_once() -> None:
    a = Interval(at(8), at(10))
    b = Interval(at(9), at(11))

    assert duration_seconds([a, b]) == 3 * 3600  # 08:00-11:00, no 4h


def test_total_seconds_counts_overlap_twice_for_data_quality_reporting() -> None:
    a = Interval(at(8), at(10))
    b = Interval(at(9), at(11))

    assert total_seconds([a, b]) == 4 * 3600
    assert total_seconds([a, b]) - duration_seconds([a, b]) == 3600
