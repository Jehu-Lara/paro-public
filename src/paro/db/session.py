"""Engine y factoria de sesiones de SQLAlchemy.

SQLite no aplica llaves foraneas por defecto: sin el ``PRAGMA foreign_keys=ON``
en cada conexion, un ``machine_id`` invalido se inserta en silencio y ninguna
prueba lo detecta hasta correr contra PostgreSQL. El listener solo actua sobre
SQLite; PostgreSQL ya aplica FKs sin configuracion adicional.
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from paro.config import get_settings

__all__ = ["get_engine", "get_session_local"]


def _register_sqlite_foreign_keys(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Builds (and caches) the engine on first use, not at import time.

    Resolving ``get_settings().database_url`` as a module-level side effect
    made importing this module order-sensitive to environment configuration
    being ready, and meant swapping the connection string always required
    reaching into a module-level object instead of a documented entry
    point. Same singleton behavior as before, just deferred to first call.
    """
    engine = create_engine(get_settings().database_url)
    _register_sqlite_foreign_keys(engine)
    return engine


@lru_cache(maxsize=1)
def get_session_local() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine())
