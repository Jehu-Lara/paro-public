"""Fixtures de integracion: base migrada con Alembic, sobre SQLite o PostgreSQL.

``alembic/env.py`` toma la URL de ``paro.config.get_settings()`` a proposito
(una sola fuente de verdad, ver TAREA 003). Por eso ambas ramas apuntan
``PARO_DATABASE_URL`` a la base bajo prueba y limpian el cache de
``get_settings`` antes y despues, en vez de inyectar la URL por otro camino
que la dejaria fuera de sincronia con el resto de la app.

Sin ``PARO_TEST_POSTGRES_URL`` la suite corre igual que hasta hoy: un archivo
SQLite temporal por prueba (pivote temporal del ADR 0002). Con la variable
puesta -- el job ``integration-postgres`` de CI, ver ADR 0003 -- corre contra
ese PostgreSQL real. Ahi la base es compartida entre pruebas y no hay archivo
que tirar, asi que el aislamiento cambia de forma: ``downgrade base`` seguido
de ``upgrade head`` antes de cada prueba.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from paro.api.deps import get_db
from paro.config import get_settings
from paro.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]

POSTGRES_URL_ENV = "PARO_TEST_POSTGRES_URL"


def _enable_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _alembic_config() -> Config:
    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return alembic_cfg


@contextmanager
def _database_url_applied(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[None]:
    """Apunta ``PARO_DATABASE_URL`` a ``database_url`` mientras corre Alembic.

    ``get_settings`` es ``lru_cache(maxsize=1)`` y puede quedar poblado por
    cualquier import previo a este punto (``paro.db.session.get_engine()``
    lo resuelve la primera vez que se llama, no al importar el modulo -- ver
    ``CHANGELOG.md``). Sin ``cache_clear()`` **antes**, ``alembic``
    leeria ese valor cacheado y migraria la base por defecto (``./paro.db``)
    ignorando esta URL -- en la rama de PostgreSQL eso seria un job en verde que
    en realidad nunca toco PostgreSQL. Sin ``cache_clear()`` **despues**, el
    valor sobrevive al ``monkeypatch`` (que restaura el entorno, no el cache) y
    se filtra a la prueba siguiente.
    """
    monkeypatch.setenv("PARO_DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _sqlite_engine(monkeypatch: pytest.MonkeyPatch) -> Generator[Engine]:
    """Un archivo SQLite temporal por prueba: el aislamiento es el archivo."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        database_url = f"sqlite:///{db_path.as_posix()}"

        with _database_url_applied(monkeypatch, database_url):
            command.upgrade(_alembic_config(), "head")

        engine = create_engine(database_url)
        event.listen(engine, "connect", _enable_foreign_keys)

        yield engine

        engine.dispose()


def _postgres_engine(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Generator[Engine]:
    """PostgreSQL real y compartido: el aislamiento es recrear el esquema.

    Las pruebas comparten la misma base, asi que cada una parte de cero con
    ``downgrade base`` (borra tablas y datos) seguido de ``upgrade head``. De
    paso ejercita el ``downgrade`` de cada migracion, que hoy no se prueba
    nunca. No se registra ``_enable_foreign_keys``: es un ``PRAGMA`` de SQLite y
    PostgreSQL ya aplica las FK sin configuracion.
    """
    with _database_url_applied(monkeypatch, database_url):
        alembic_cfg = _alembic_config()
        command.downgrade(alembic_cfg, "base")
        command.upgrade(alembic_cfg, "head")

    engine = create_engine(database_url)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        raise RuntimeError(
            f"{POSTGRES_URL_ENV} debe apuntar a PostgreSQL, no a "
            f"{engine.dialect.name!r}. Formato esperado: "
            "postgresql+psycopg://usuario:password@host:puerto/base"
        )

    yield engine

    engine.dispose()


@pytest.fixture
def migrated_engine(monkeypatch: pytest.MonkeyPatch) -> Generator[Engine]:
    """Entrega un ``Engine`` sobre una base recien migrada a ``head``.

    El motor lo decide el entorno, no la prueba: las pruebas de integracion no
    saben contra que base corren y por eso valen igual en ambas.
    """
    postgres_url = os.environ.get(POSTGRES_URL_ENV)
    if postgres_url:
        yield from _postgres_engine(monkeypatch, postgres_url)
    else:
        yield from _sqlite_engine(monkeypatch)


@pytest.fixture
def client(migrated_engine: Engine) -> Generator[TestClient]:
    """``TestClient`` sobre ``migrated_engine``, nunca sobre ``./paro.db`` real.

    ``get_db`` queda sobreescrito con una sesion nueva por request (no una
    compartida entre llamadas), igual que en produccion.
    """

    def override_get_db() -> Generator[Session]:
        with Session(migrated_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
