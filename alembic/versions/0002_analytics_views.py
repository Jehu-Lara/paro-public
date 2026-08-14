"""analytics views for Power BI

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQL especifico por dialecto solo para la resta de timestamps: no hay
    # forma portable de obtener segundos entre dos UTCDateTime en SQL puro.
    # Ver ADR 0002 (mitigacion 4) - esa mitigacion protege que revertir el
    # pivote a SQLite sea solo un cambio de connection string; esta capa es
    # nueva y aditiva, no parte de ese esquema reversible. Se redondea a
    # segundo entero (CAST ... AS INTEGER) en vez de dejar float: evita
    # ambiguedad de tipo Decimal/float entre dialectos y de paso elimina el
    # ruido de punto flotante de julianday() en SQLite.
    is_sqlite = op.get_bind().dialect.name == "sqlite"

    downtime_duration_expr = (
        "CAST(ROUND((julianday(de.ended_at) - julianday(de.started_at)) * 86400.0) AS INTEGER)"
        if is_sqlite
        else "CAST(ROUND(EXTRACT(EPOCH FROM (de.ended_at - de.started_at))) AS INTEGER)"
    )
    interval_duration_expr = (
        "CAST(ROUND((julianday(pr.interval_end) - julianday(pr.interval_start)) * 86400.0)"
        " AS INTEGER)"
        if is_sqlite
        else "CAST(ROUND(EXTRACT(EPOCH FROM (pr.interval_end - pr.interval_start))) AS INTEGER)"
    )

    op.execute(
        sa.text(
            f"""
            CREATE VIEW fact_downtime_event AS
            SELECT
                de.id AS downtime_event_id,
                pl.id AS line_id,
                pl.code AS line_code,
                pl.name AS line_name,
                pl.timezone AS line_timezone,
                m.id AS machine_id,
                m.code AS machine_code,
                m.name AS machine_name,
                dr.id AS reason_id,
                dr.code AS reason_code,
                dr.name AS reason_name,
                de.started_at AS started_at,
                de.ended_at AS ended_at,
                de.is_planned AS is_planned,
                {downtime_duration_expr} AS duration_seconds,
                de.operator_note AS operator_note,
                de.source AS source,
                de.external_id AS external_id,
                de.created_at AS created_at,
                de.updated_at AS updated_at
            FROM downtime_event de
            JOIN production_line pl ON pl.id = de.line_id
            JOIN downtime_reason dr ON dr.id = de.reason_id
            LEFT JOIN machine m ON m.id = de.machine_id
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            CREATE VIEW fact_production_record AS
            SELECT
                pr.id AS production_record_id,
                pl.id AS line_id,
                pl.code AS line_code,
                pl.name AS line_name,
                pl.timezone AS line_timezone,
                pr.interval_start AS interval_start,
                pr.interval_end AS interval_end,
                {interval_duration_expr} AS interval_duration_seconds,
                pr.total_count AS total_count,
                pr.good_count AS good_count,
                (pr.total_count - pr.good_count) AS rejected_count,
                pr.ideal_cycle_time_seconds AS ideal_cycle_time_seconds,
                pr.source AS source,
                pr.external_id AS external_id,
                pr.created_at AS created_at,
                pr.updated_at AS updated_at
            FROM production_record pr
            JOIN production_line pl ON pl.id = pr.line_id
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP VIEW IF EXISTS fact_production_record"))
    op.execute(sa.text("DROP VIEW IF EXISTS fact_downtime_event"))
