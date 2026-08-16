"""``alembic upgrade head`` sobre una base vacia crea el esquema completo."""

from __future__ import annotations

from sqlalchemy import Engine, inspect

EXPECTED_TABLES = {
    "production_line",
    "machine",
    "downtime_reason",
    "shift",
    "downtime_event",
    "production_record",
    "audit_log",
}


def test_upgrade_head_creates_all_tables(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)

    # alembic_version es la tabla de control de Alembic, no parte del esquema.
    assert set(inspector.get_table_names()) - {"alembic_version"} == EXPECTED_TABLES


def test_upgrade_head_creates_expected_indexes(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)

    downtime_event_indexes = {ix["name"] for ix in inspector.get_indexes("downtime_event")}
    production_record_indexes = {ix["name"] for ix in inspector.get_indexes("production_record")}
    audit_log_indexes = {ix["name"] for ix in inspector.get_indexes("audit_log")}

    assert "ix_downtime_event_line_id_started_at" in downtime_event_indexes
    assert "ix_production_record_line_id_interval_start" in production_record_indexes
    assert "ix_audit_log_downtime_event_id" in audit_log_indexes
