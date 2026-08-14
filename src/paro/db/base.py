"""Base declarativa de SQLAlchemy con convencion de nombres estable.

Sin ``naming_convention`` cada dialecto (y cada version de Alembic) puede
generar nombres de constraint distintos para el mismo esquema logico, lo que
rompe el autogenerate al comparar contra una migracion ya aplicada. Fijar la
convencion aqui hace que los nombres sean identicos en SQLite y PostgreSQL.
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
    """Clase base declarativa compartida por todos los modelos del dominio."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
