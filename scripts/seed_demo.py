"""Datos de demo deterministas para desarrollo local.

Seguro de correr mas de una vez: las tablas de catalogo (linea, maquina,
motivo, turno) se buscan por su clave natural antes de insertar, y los
eventos de paro / registros de produccion pasan por los repositorios
idempotentes de ``paro.db.repositories`` (clave ``source`` + ``external_id``).
Ninguna corrida duplica filas.

Todos los timestamps son literales fijos en UTC: usar ``datetime.now()`` haria
que dos corridas del script no produjeran los mismos datos.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paro.db.models import (
    DowntimeEvent,
    DowntimeReason,
    Machine,
    ProductionLine,
    ProductionRecord,
    Shift,
)
from paro.db.repositories import create_downtime_event, create_production_record
from paro.db.session import get_session_local

__all__ = ["main", "run"]

SOURCE = "seed_demo"

LINE_CODE = "L1"
MACHINE_CODE_1 = "M1"
MACHINE_CODE_2 = "M2"
REASON_PLANNED_CODE = "MTN-P"
REASON_UNPLANNED_CODE = "FLA-M"
REASON_PLANNED_CHANGEOVER_CODE = "CHG-P"
REASON_FAILURE_ELECTRICAL_CODE = "FLA-E"
REASON_FAILURE_PNEUMATIC_CODE = "FLA-N"
REASON_FAILURE_SENSOR_CODE = "FLA-S"
REASON_MICRO_STOP_MATERIAL_JAM_CODE = "ATC-M"
REASON_MICRO_STOP_STARVATION_CODE = "DES-M"
REASON_MICRO_STOP_MINOR_ADJUSTMENT_CODE = "AJT-M"
SHIFT_CODE = "T1"

# El turno cruza medianoche a proposito: 2026-08-10 22:00 UTC -> 2026-08-11 06:00 UTC.
SHIFT_BUSINESS_DATE = date(2026, 8, 10)
SHIFT_START = datetime(2026, 8, 10, 22, 0, tzinfo=UTC)
SHIFT_END = datetime(2026, 8, 11, 6, 0, tzinfo=UTC)

PLANNED_EVENT_START = datetime(2026, 8, 10, 23, 0, tzinfo=UTC)
PLANNED_EVENT_END = datetime(2026, 8, 10, 23, 15, tzinfo=UTC)

# Se solapan a proposito (01:15-01:30 compartido) para dejar un caso real de
# union de intervalos para el Pareto de Sprint 4.
OVERLAP_EVENT_1_START = datetime(2026, 8, 11, 1, 0, tzinfo=UTC)
OVERLAP_EVENT_1_END = datetime(2026, 8, 11, 1, 30, tzinfo=UTC)
OVERLAP_EVENT_2_START = datetime(2026, 8, 11, 1, 15, tzinfo=UTC)
OVERLAP_EVENT_2_END = datetime(2026, 8, 11, 1, 45, tzinfo=UTC)

OPEN_EVENT_START = datetime(2026, 8, 11, 5, 0, tzinfo=UTC)

RECORD_INTERVAL_START = SHIFT_START
RECORD_INTERVAL_END = SHIFT_END

TABLES: dict[str, type[Any]] = {
    "production_line": ProductionLine,
    "machine": Machine,
    "downtime_reason": DowntimeReason,
    "shift": Shift,
    "downtime_event": DowntimeEvent,
    "production_record": ProductionRecord,
}


def _get_or_create_line(session: Session) -> ProductionLine:
    existing = session.execute(
        select(ProductionLine).where(ProductionLine.code == LINE_CODE)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    line = ProductionLine(code=LINE_CODE, name="Linea 1", timezone="America/Monterrey", active=True)
    session.add(line)
    session.flush()
    return line


def _get_or_create_machine(session: Session, line: ProductionLine, code: str) -> Machine:
    existing = session.execute(
        select(Machine).where(Machine.line_id == line.id, Machine.code == code)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    machine = Machine(line_id=line.id, code=code, name=f"Maquina {code}")
    session.add(machine)
    session.flush()
    return machine


def _get_or_create_reason(
    session: Session, code: str, name: str, default_is_planned: bool
) -> DowntimeReason:
    existing = session.execute(
        select(DowntimeReason).where(DowntimeReason.code == code)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    reason = DowntimeReason(code=code, name=name, default_is_planned=default_is_planned)
    session.add(reason)
    session.flush()
    return reason


def _get_or_create_shift(session: Session, line: ProductionLine) -> Shift:
    """Busca por clave natural: la tabla ``shift`` no tiene UNIQUE (ver ADR 0002).

    Sin esta busqueda previa, correr el script dos veces crearia un turno
    duplicado en cada corrida.
    """
    existing = session.execute(
        select(Shift).where(
            Shift.line_id == line.id,
            Shift.code == SHIFT_CODE,
            Shift.business_date == SHIFT_BUSINESS_DATE,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    shift = Shift(
        line_id=line.id,
        code=SHIFT_CODE,
        business_date=SHIFT_BUSINESS_DATE,
        planned_start_utc=SHIFT_START,
        planned_end_utc=SHIFT_END,
        planned_break_minutes=30,
    )
    session.add(shift)
    session.flush()
    return shift


def _counts(session: Session) -> dict[str, int]:
    return {
        name: session.scalar(select(func.count()).select_from(model)) or 0
        for name, model in TABLES.items()
    }


def run(session: Session) -> dict[str, int]:
    """Siembra los datos de demo en ``session`` y devuelve conteos por tabla.

    Segura de llamar dos veces sobre la misma base: catalogos por clave
    natural, eventos/registros por los repositorios idempotentes.
    """
    line = _get_or_create_line(session)
    machine_1 = _get_or_create_machine(session, line, MACHINE_CODE_1)
    _get_or_create_machine(session, line, MACHINE_CODE_2)
    reason_planned = _get_or_create_reason(
        session, REASON_PLANNED_CODE, "Mantenimiento planeado", True
    )
    reason_unplanned = _get_or_create_reason(
        session, REASON_UNPLANNED_CODE, "Falla mecanica", False
    )
    # Las 7 filas siguientes completan el catalogo que necesita el reason mix
    # del simulador (docs/simulator-spec.md 4.6): FLA-M ya cubre "mechanical"
    # (clase failure); CHG-P es un motivo planeado propio, distinto de MTN-P
    # a proposito (mantenimiento vs. cambio de formato/producto).
    _get_or_create_reason(session, REASON_PLANNED_CHANGEOVER_CODE, "Cambio de formato", True)
    _get_or_create_reason(session, REASON_FAILURE_ELECTRICAL_CODE, "Falla electrica", False)
    _get_or_create_reason(session, REASON_FAILURE_PNEUMATIC_CODE, "Falla neumatica", False)
    _get_or_create_reason(session, REASON_FAILURE_SENSOR_CODE, "Falla de sensor", False)
    _get_or_create_reason(
        session, REASON_MICRO_STOP_MATERIAL_JAM_CODE, "Atasco de material", False
    )
    _get_or_create_reason(
        session, REASON_MICRO_STOP_STARVATION_CODE, "Desabasto de material", False
    )
    _get_or_create_reason(
        session, REASON_MICRO_STOP_MINOR_ADJUSTMENT_CODE, "Ajuste menor", False
    )
    _get_or_create_shift(session, line)

    _, was_created_first = create_downtime_event(
        session,
        line_id=line.id,
        machine_id=machine_1.id,
        reason_id=reason_planned.id,
        started_at=PLANNED_EVENT_START,
        ended_at=PLANNED_EVENT_END,
        is_planned=True,
        source=SOURCE,
        external_id="downtime-planned-1",
    )
    print(f"[seed_demo] downtime-planned-1: 1ra llamada was_created={was_created_first}")
    _, was_created_second = create_downtime_event(
        session,
        line_id=line.id,
        machine_id=machine_1.id,
        reason_id=reason_planned.id,
        started_at=PLANNED_EVENT_START,
        ended_at=PLANNED_EVENT_END,
        is_planned=True,
        source=SOURCE,
        external_id="downtime-planned-1",
    )
    print(
        f"[seed_demo] downtime-planned-1: 2da llamada (mismo payload) "
        f"was_created={was_created_second} (idempotencia demostrada)"
    )

    create_downtime_event(
        session,
        line_id=line.id,
        machine_id=machine_1.id,
        reason_id=reason_unplanned.id,
        started_at=OVERLAP_EVENT_1_START,
        ended_at=OVERLAP_EVENT_1_END,
        is_planned=False,
        source=SOURCE,
        external_id="downtime-overlap-1",
    )
    create_downtime_event(
        session,
        line_id=line.id,
        machine_id=machine_1.id,
        reason_id=reason_unplanned.id,
        started_at=OVERLAP_EVENT_2_START,
        ended_at=OVERLAP_EVENT_2_END,
        is_planned=False,
        source=SOURCE,
        external_id="downtime-overlap-2",
    )
    create_downtime_event(
        session,
        line_id=line.id,
        machine_id=machine_1.id,
        reason_id=reason_unplanned.id,
        started_at=OPEN_EVENT_START,
        ended_at=None,
        is_planned=False,
        source=SOURCE,
        external_id="downtime-open-1",
    )

    create_production_record(
        session,
        line_id=line.id,
        interval_start=RECORD_INTERVAL_START,
        interval_end=RECORD_INTERVAL_END,
        total_count=5000,
        good_count=4800,
        ideal_cycle_time_seconds=Decimal("5.500"),
        source=SOURCE,
        external_id="production-record-1",
    )

    session.commit()
    return _counts(session)


def _print_summary(counts: dict[str, int]) -> None:
    print("[seed_demo] Conteo de filas por tabla:")
    for name, count in counts.items():
        print(f"  {name}: {count}")


def main() -> None:
    with get_session_local()() as session:
        counts = run(session)
    _print_summary(counts)


if __name__ == "__main__":
    main()
