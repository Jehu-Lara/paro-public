"""Engine y factoria de sesiones de SQLAlchemy.

SQLite no aplica llaves foraneas por defecto: sin el ``PRAGMA foreign_keys=ON``
en cada conexion, un ``machine_id`` invalido se inserta en silencio y ninguna
prueba lo detecta hasta correr contra PostgreSQL. El listener solo actua sobre
SQLite; PostgreSQL ya aplica FKs sin configuracion adicional.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from paro.config import get_settings

__all__ = ["SessionLocal", "engine"]


def _make_engine() -> Engine:
    return create_engine(get_settings().database_url)


engine: Engine = _make_engine()
SessionLocal: sessionmaker[Session] = sessionmaker(bind=engine)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
