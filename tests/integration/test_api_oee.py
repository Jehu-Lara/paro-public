"""``GET /api/v1/oee``: la respuesta debe coincidir exactamente con una
llamada directa a ``domain/oee.py.calculate_oee`` sobre los mismos datos.
Tambien cubre linea inexistente (404), ventana sin datos (200 con warnings)
y exclusion de registros de produccion parcialmente solapados.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from paro.api.routers.oee import _ideal_time_total_seconds, get_oee
from paro.db.models import DowntimeEvent, DowntimeReason, ProductionLine, ProductionRecord
from paro.domain.intervals import Interval
from paro.domain.oee import DowntimeSpan, calculate_oee

WINDOW_START = datetime(2026, 8, 10, 22, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 8, 11, 6, 0, tzinfo=UTC)

PLANNED_START = datetime(2026, 8, 10, 23, 0, tzinfo=UTC)
PLANNED_END = datetime(2026, 8, 10, 23, 15, tzinfo=UTC)

OVERLAP_1_START = datetime(2026, 8, 11, 1, 0, tzinfo=UTC)
OVERLAP_1_END = datetime(2026, 8, 11, 1, 30, tzinfo=UTC)
OVERLAP_2_START = datetime(2026, 8, 11, 1, 15, tzinfo=UTC)
OVERLAP_2_END = datetime(2026, 8, 11, 1, 45, tzinfo=UTC)

OPEN_START = datetime(2026, 8, 11, 5, 0, tzinfo=UTC)

# Parcialmente fuera de la ventana (empieza antes de WINDOW_START): debe excluirse entero.
PARTIAL_RECORD_START = WINDOW_START - timedelta(minutes=30)
PARTIAL_RECORD_END = WINDOW_START + timedelta(minutes=30)


def _seed_line(session: Session) -> ProductionLine:
    line = ProductionLine(code="L1", name="Linea 1", timezone="America/Monterrey", active=True)
    session.add(line)
    session.flush()
    return line


def _seed_reasons(session: Session) -> tuple[DowntimeReason, DowntimeReason]:
    planned = DowntimeReason(code="MTN-P", name="Mantenimiento planeado", default_is_planned=True)
    unplanned = DowntimeReason(code="FLA-M", name="Falla mecanica", default_is_planned=False)
    session.add_all([planned, unplanned])
    session.flush()
    return planned, unplanned


def _seed_full_scenario(session: Session) -> ProductionLine:
    line = _seed_line(session)
    reason_planned, reason_unplanned = _seed_reasons(session)

    session.add_all(
        [
            DowntimeEvent(
                line_id=line.id,
                started_at=PLANNED_START,
                ended_at=PLANNED_END,
                reason_id=reason_planned.id,
                is_planned=True,
            ),
            DowntimeEvent(
                line_id=line.id,
                started_at=OVERLAP_1_START,
                ended_at=OVERLAP_1_END,
                reason_id=reason_unplanned.id,
                is_planned=False,
            ),
            DowntimeEvent(
                line_id=line.id,
                started_at=OVERLAP_2_START,
                ended_at=OVERLAP_2_END,
                reason_id=reason_unplanned.id,
                is_planned=False,
            ),
            DowntimeEvent(
                line_id=line.id,
                started_at=OPEN_START,
                ended_at=None,
                reason_id=reason_unplanned.id,
                is_planned=False,
            ),
            ProductionRecord(
                line_id=line.id,
                interval_start=WINDOW_START,
                interval_end=WINDOW_END,
                total_count=5000,
                good_count=4800,
                ideal_cycle_time_seconds=Decimal("5.500"),
            ),
            ProductionRecord(
                line_id=line.id,
                interval_start=WINDOW_START,
                interval_end=WINDOW_START + timedelta(hours=1),
                total_count=100,
                good_count=95,
                ideal_cycle_time_seconds=Decimal("10.000"),
            ),
            # Parcialmente fuera de [WINDOW_START, WINDOW_END): debe excluirse.
            ProductionRecord(
                line_id=line.id,
                interval_start=PARTIAL_RECORD_START,
                interval_end=PARTIAL_RECORD_END,
                total_count=9999,
                good_count=1,
                ideal_cycle_time_seconds=Decimal("999.000"),
            ),
        ]
    )
    session.commit()
    return line


def _decimal_field(payload: dict[str, object], key: str) -> Decimal | None:
    value = payload[key]
    assert value is None or isinstance(value, str), (
        f"{key} debe ser None o string, no {type(value)}"
    )
    return None if value is None else Decimal(value)


def test_get_oee_matches_direct_domain_call(client: TestClient, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        line = _seed_full_scenario(session)
        line_id = line.id

    response = client.get(
        "/api/v1/oee",
        params={
            "line_id": line_id,
            "start": WINDOW_START.isoformat(),
            "end": WINDOW_END.isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()

    # Solo los dos registros totalmente contenidos participan; el parcial se excluye.
    total_count = 5000 + 100
    good_count = 4800 + 95
    # Exact sum, never divided by total_count (see B1 / domain/oee.py).
    ideal_time_total_seconds = Decimal("5.500") * 5000 + Decimal("10.000") * 100

    expected = calculate_oee(
        window=Interval(WINDOW_START, WINDOW_END),
        planned_downtimes=[DowntimeSpan(start=PLANNED_START, end=PLANNED_END)],
        unplanned_downtimes=[
            DowntimeSpan(start=OVERLAP_1_START, end=OVERLAP_1_END),
            DowntimeSpan(start=OVERLAP_2_START, end=OVERLAP_2_END),
            DowntimeSpan(start=OPEN_START, end=None),
        ],
        total_count=total_count,
        good_count=good_count,
        ideal_time_total_seconds=ideal_time_total_seconds,
    )

    assert body["line_id"] == line_id
    assert _decimal_field(body, "availability") == expected.availability
    assert _decimal_field(body, "performance_raw") == expected.performance_raw
    assert _decimal_field(body, "performance_capped") == expected.performance_capped
    assert _decimal_field(body, "quality") == expected.quality
    assert _decimal_field(body, "oee") == expected.oee
    assert body["planned_production_time_seconds"] == expected.planned_production_time_seconds
    assert body["run_time_seconds"] == expected.run_time_seconds
    assert body["warnings"] == expected.warnings
    assert "OPEN_EVENT_CLIPPED" in body["warnings"]

    # window_start/window_end deben llevar offset UTC explicito.
    for key in ("window_start", "window_end"):
        raw = body[key]
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        assert parsed.utcoffset() == timedelta(0)


def test_ideal_time_total_seconds_sums_exactly_without_averaging(
    migrated_engine: Engine,
) -> None:
    """``_ideal_time_total_seconds`` must sum exactly, never average and round.

    Three records with ``total_count=1`` each and ``ideal_cycle_time_seconds``
    10/10/30 (contributions 10, 10, 30) give a per-unit weighted average of
    50/3, a non-terminating decimal. Verified empirically that dividing by 3
    and multiplying back by 3 does NOT reproduce 50 exactly under
    ``Decimal``'s default context (drifts by ``1E-26``): that is precisely
    the round-trip this function must never perform.
    """
    with Session(migrated_engine) as session:
        line = _seed_line(session)
        session.add_all(
            [
                ProductionRecord(
                    line_id=line.id,
                    interval_start=WINDOW_START,
                    interval_end=WINDOW_END,
                    total_count=1,
                    good_count=1,
                    ideal_cycle_time_seconds=Decimal("10.000"),
                ),
                ProductionRecord(
                    line_id=line.id,
                    interval_start=WINDOW_START,
                    interval_end=WINDOW_END,
                    total_count=1,
                    good_count=1,
                    ideal_cycle_time_seconds=Decimal("10.000"),
                ),
                ProductionRecord(
                    line_id=line.id,
                    interval_start=WINDOW_START,
                    interval_end=WINDOW_END,
                    total_count=1,
                    good_count=1,
                    ideal_cycle_time_seconds=Decimal("30.000"),
                ),
            ]
        )
        session.commit()
        line_id = line.id

    with Session(migrated_engine) as session:
        records = list(
            session.scalars(
                select(ProductionRecord).where(
                    ProductionRecord.line_id == line_id,
                    ProductionRecord.interval_start >= WINDOW_START,
                    ProductionRecord.interval_end <= WINDOW_END,
                )
            ).all()
        )

    assert _ideal_time_total_seconds(records) == Decimal(50)

    # Why this matters: dividing by 3 and multiplying back by 3 does not
    # reproduce 50 exactly under Decimal's default context -- the round-trip
    # this function avoids by construction.
    lossy_round_trip = (Decimal(50) / Decimal(3)) * 3
    assert lossy_round_trip != Decimal(50)


def test_get_oee_unknown_line_returns_404(client: TestClient) -> None:
    response = client.get(
        "/api/v1/oee",
        params={
            "line_id": 999,
            "start": WINDOW_START.isoformat(),
            "end": WINDOW_END.isoformat(),
        },
    )
    assert response.status_code == 404


def test_get_oee_line_without_data_returns_200_with_warnings(
    client: TestClient, migrated_engine: Engine
) -> None:
    with Session(migrated_engine) as session:
        line = _seed_line(session)
        session.commit()
        line_id = line.id

    response = client.get(
        "/api/v1/oee",
        params={
            "line_id": line_id,
            "start": WINDOW_START.isoformat(),
            "end": WINDOW_END.isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()

    expected = calculate_oee(
        window=Interval(WINDOW_START, WINDOW_END),
        planned_downtimes=[],
        unplanned_downtimes=[],
        total_count=0,
        good_count=0,
        ideal_time_total_seconds=Decimal("0"),
    )

    assert expected.quality is None
    assert _decimal_field(body, "quality") is None
    assert body["warnings"] == expected.warnings
    assert "ZERO_TOTAL_COUNT" in body["warnings"]


def test_get_oee_rejects_naive_datetime(client: TestClient, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        line = _seed_line(session)
        session.commit()
        line_id = line.id

    response = client.get(
        "/api/v1/oee",
        params={"line_id": line_id, "start": "2026-08-10T22:00:00", "end": WINDOW_END.isoformat()},
    )
    assert response.status_code == 422


def test_get_oee_rejects_end_before_start(client: TestClient, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        line = _seed_line(session)
        session.commit()
        line_id = line.id

    response = client.get(
        "/api/v1/oee",
        params={
            "line_id": line_id,
            "start": WINDOW_END.isoformat(),
            "end": WINDOW_START.isoformat(),
        },
    )
    assert response.status_code == 422


class _BrokenTzinfo(tzinfo):
    """Same broken ``tzinfo`` as ``tests/unit/test_intervals.py``: not
    ``None``, but ``utcoffset()`` is. No real HTTP query string can produce
    this -- Pydantic only ever builds ``datetime.timezone`` (valid offset)
    or leaves the datetime naive -- so this can't be reproduced through
    ``TestClient``. Calls the actual router function directly instead.
    """

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "broken"


# NOTE: calls the router function directly, not via HTTP -- see docstring.
def test_get_oee_rejects_tzinfo_with_none_utcoffset_as_422_not_500(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        line = _seed_line(session)
        session.commit()
        line_id = line.id

    broken_start = datetime(2026, 8, 10, 22, 0, tzinfo=_BrokenTzinfo())

    with Session(migrated_engine) as session, pytest.raises(HTTPException) as exc_info:
        get_oee(line_id=line_id, start=broken_start, end=WINDOW_END, db=session)

    assert exc_info.value.status_code == 422
