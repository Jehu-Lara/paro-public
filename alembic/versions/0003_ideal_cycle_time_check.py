"""ideal cycle time check

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-13 23:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SQLite has no ALTER TABLE ADD CONSTRAINT: batch mode recreates the whole
# table (copy, drop, rename). fact_production_record (migration 0002)
# depends on production_record, so it must be dropped before the recreate
# and rebuilt after with the identical definition, or the rename step fails
# ("no such table: main.production_record") because the view is left
# referencing a table that briefly doesn't exist. PostgreSQL's plain ADD
# CONSTRAINT never touches the physical table, so none of this applies there.
_FACT_PRODUCTION_RECORD_VIEW = """
    CREATE VIEW fact_production_record AS
    SELECT
        pr.id AS production_record_id,
        pl.id AS line_id,
        pl.code AS line_code,
        pl.name AS line_name,
        pl.timezone AS line_timezone,
        pr.interval_start AS interval_start,
        pr.interval_end AS interval_end,
        CAST(ROUND((julianday(pr.interval_end) - julianday(pr.interval_start)) * 86400.0)
            AS INTEGER) AS interval_duration_seconds,
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


def upgrade() -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"

    if is_sqlite:
        op.execute(sa.text("DROP VIEW fact_production_record"))
        with op.batch_alter_table("production_record") as batch_op:
            batch_op.create_check_constraint(
                op.f("ck_production_record_valid_ideal_cycle_time"),
                "ideal_cycle_time_seconds >= 0",
            )
        op.execute(sa.text(_FACT_PRODUCTION_RECORD_VIEW))
    else:
        op.create_check_constraint(
            op.f("ck_production_record_valid_ideal_cycle_time"),
            "production_record",
            "ideal_cycle_time_seconds >= 0",
        )


def downgrade() -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"

    if is_sqlite:
        op.execute(sa.text("DROP VIEW fact_production_record"))
        with op.batch_alter_table("production_record") as batch_op:
            batch_op.drop_constraint(
                op.f("ck_production_record_valid_ideal_cycle_time"), type_="check"
            )
        op.execute(sa.text(_FACT_PRODUCTION_RECORD_VIEW))
    else:
        op.drop_constraint(
            op.f("ck_production_record_valid_ideal_cycle_time"),
            "production_record",
            type_="check",
        )
