"""audit log

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-15 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import paro.db.types

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("downtime_event_id", sa.Integer(), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=True),
        sa.Column("changed_at", paro.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["downtime_event_id"],
            ["downtime_event.id"],
            name=op.f("fk_audit_log_downtime_event_id_downtime_event"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_index("ix_audit_log_downtime_event_id", ["downtime_event_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_index("ix_audit_log_downtime_event_id")

    op.drop_table("audit_log")
