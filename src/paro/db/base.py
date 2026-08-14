"""SQLAlchemy declarative base with a stable naming convention.

Without ``naming_convention``, each dialect (and each Alembic version) can
generate different constraint names for the same logical schema, breaking
autogenerate when comparing against an already-applied migration. Fixing
the convention here makes the names identical on SQLite and PostgreSQL.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base class shared by every domain model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
