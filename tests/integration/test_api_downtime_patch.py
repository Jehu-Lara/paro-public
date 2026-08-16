"""``PATCH /api/v1/downtime-events/{id}``: correcciones parciales, concurrencia
optimista (409) y el ``audit_log`` que resulta de cada cambio real.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from paro.db.models import AuditLog, DowntimeEvent, DowntimeReason, Machine, ProductionLine

STARTED_AT = datetime(2026, 8, 10, 22, 0, tzinfo=UTC)
ENDED_AT = datetime(2026, 8, 10, 22, 5, tzinfo=UTC)


def _seed_event(migrated_engine: Engine) -> tuple[int, int, int]:
    """Crea linea + motivo + evento; devuelve ``(event_id, line_id, reason_id)``."""
    with Session(migrated_engine) as session:
        line = ProductionLine(code="L1", name="Linea 1", timezone="America/Monterrey", active=True)
        reason = DowntimeReason(code="R1", name="Falla mecanica", default_is_planned=False)
        session.add_all([line, reason])
        session.flush()
        event = DowntimeEvent(
            line_id=line.id,
            started_at=STARTED_AT,
            ended_at=ENDED_AT,
            reason_id=reason.id,
            is_planned=False,
            operator_note="original",
        )
        session.add(event)
        session.commit()
        return event.id, line.id, reason.id


def _current_updated_at(migrated_engine: Engine, event_id: int) -> str:
    with Session(migrated_engine) as session:
        event = session.get(DowntimeEvent, event_id)
        assert event is not None
        return event.updated_at.isoformat()


def test_patch_changes_field_and_writes_audit_log(
    client: TestClient, migrated_engine: Engine
) -> None:
    event_id, _, _ = _seed_event(migrated_engine)
    expected_updated_at = _current_updated_at(migrated_engine, event_id)

    response = client.patch(
        f"/api/v1/downtime-events/{event_id}",
        json={
            "expected_updated_at": expected_updated_at,
            "operator_note": "corrected",
            "actor": "supervisor@example.com",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operator_note"] == "corrected"
    assert datetime.fromisoformat(body["updated_at"]) > datetime.fromisoformat(expected_updated_at)

    with Session(migrated_engine) as session:
        count = session.scalar(select(func.count()).select_from(AuditLog))
        assert count == 1
        log = session.scalars(select(AuditLog)).one()
        assert log.downtime_event_id == event_id
        assert log.actor == "supervisor@example.com"
        assert log.changed_fields == {"operator_note": ["original", "corrected"]}


def test_patch_stale_expected_updated_at_returns_409(
    client: TestClient, migrated_engine: Engine
) -> None:
    event_id, _, _ = _seed_event(migrated_engine)
    stale = datetime(2020, 1, 1, tzinfo=UTC).isoformat()

    response = client.patch(
        f"/api/v1/downtime-events/{event_id}",
        json={"expected_updated_at": stale, "operator_note": "corrected"},
    )

    assert response.status_code == 409
    assert response.json()["error"] == "stale_update"

    with Session(migrated_engine) as session:
        count = session.scalar(select(func.count()).select_from(AuditLog))
        assert count == 0


def test_patch_same_values_is_a_noop(client: TestClient, migrated_engine: Engine) -> None:
    event_id, _, _ = _seed_event(migrated_engine)
    expected_updated_at = _current_updated_at(migrated_engine, event_id)

    response = client.patch(
        f"/api/v1/downtime-events/{event_id}",
        json={"expected_updated_at": expected_updated_at, "operator_note": "original"},
    )

    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()["updated_at"]) == datetime.fromisoformat(
        expected_updated_at
    )

    with Session(migrated_engine) as session:
        count = session.scalar(select(func.count()).select_from(AuditLog))
        assert count == 0


def test_patch_unknown_event_returns_404(client: TestClient, migrated_engine: Engine) -> None:
    response = client.patch(
        "/api/v1/downtime-events/999999",
        json={
            "expected_updated_at": datetime.now(UTC).isoformat(),
            "operator_note": "corrected",
        },
    )

    assert response.status_code == 404


def test_patch_unknown_machine_returns_404(client: TestClient, migrated_engine: Engine) -> None:
    event_id, _, _ = _seed_event(migrated_engine)
    expected_updated_at = _current_updated_at(migrated_engine, event_id)

    response = client.patch(
        f"/api/v1/downtime-events/{event_id}",
        json={"expected_updated_at": expected_updated_at, "machine_id": 999999},
    )

    assert response.status_code == 404


def test_patch_unknown_reason_returns_404(client: TestClient, migrated_engine: Engine) -> None:
    event_id, _, _ = _seed_event(migrated_engine)
    expected_updated_at = _current_updated_at(migrated_engine, event_id)

    response = client.patch(
        f"/api/v1/downtime-events/{event_id}",
        json={"expected_updated_at": expected_updated_at, "reason_id": 999999},
    )

    assert response.status_code == 404


def test_patch_merged_ended_at_before_started_at_returns_422(
    client: TestClient, migrated_engine: Engine
) -> None:
    event_id, _, _ = _seed_event(migrated_engine)
    expected_updated_at = _current_updated_at(migrated_engine, event_id)

    response = client.patch(
        f"/api/v1/downtime-events/{event_id}",
        json={
            "expected_updated_at": expected_updated_at,
            "ended_at": datetime(2026, 8, 10, 21, 0, tzinfo=UTC).isoformat(),
        },
    )

    assert response.status_code == 422


def test_patch_naive_expected_updated_at_returns_422(
    client: TestClient, migrated_engine: Engine
) -> None:
    event_id, _, _ = _seed_event(migrated_engine)

    response = client.patch(
        f"/api/v1/downtime-events/{event_id}",
        json={"expected_updated_at": "2026-08-10T22:00:00", "operator_note": "corrected"},
    )

    assert response.status_code == 422


def test_patch_machine_id_reference(client: TestClient, migrated_engine: Engine) -> None:
    event_id, line_id, _ = _seed_event(migrated_engine)
    expected_updated_at = _current_updated_at(migrated_engine, event_id)
    with Session(migrated_engine) as session:
        machine = Machine(line_id=line_id, code="M1", name="Maquina 1")
        session.add(machine)
        session.commit()
        machine_id = machine.id

    response = client.patch(
        f"/api/v1/downtime-events/{event_id}",
        json={"expected_updated_at": expected_updated_at, "machine_id": machine_id},
    )

    assert response.status_code == 200
    assert response.json()["machine_id"] == machine_id
