"""paro.db.session: engine/sessionmaker construction is lazy and cached, not
built as an import-time side effect. Real production wiring (get_db) has no
coverage elsewhere in this suite -- the client fixture always overrides
get_db, and test_seed_demo.py never calls seed_demo.main() -- so this file
exercises the real code path directly.
"""

from __future__ import annotations

import importlib.util
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text

import paro.db.session as session_module
from paro.config import get_settings


def _load_fresh_copy() -> object:
    """Executes db/session.py as an independent module object, never
    registered in sys.modules -- so it can't disturb api.deps' already-bound
    references to the real paro.db.session, unlike importlib.reload would.
    """
    spec = importlib.util.spec_from_file_location(
        "paro.db._session_test_copy", session_module.__file__
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_get_engine_is_lazy_and_cached() -> None:
    with patch("sqlalchemy.create_engine") as mock_create_engine:
        mock_create_engine.return_value = create_engine("sqlite:///:memory:")

        fresh = _load_fresh_copy()
        mock_create_engine.assert_not_called()  # import alone builds nothing

        # _load_fresh_copy() returns object on purpose (see its docstring):
        # mypy can't know the dynamically loaded module's shape statically.
        first = fresh.get_engine()  # type: ignore[attr-defined]
        mock_create_engine.assert_called_once()

        second = fresh.get_engine()  # type: ignore[attr-defined]
        assert second is first
        mock_create_engine.assert_called_once()  # still once: cached, not rebuilt


@pytest.fixture
def _sqlite_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Points PARO_DATABASE_URL at a temp SQLite file and clears every
    lru_cache that could otherwise leak a stale engine/sessionmaker/settings
    into another test -- in a finally, so a failed assertion mid-test still
    cleans up. Disposes the engine before the temp directory is removed:
    a lingering open connection can make the directory cleanup fail on
    Windows (same pattern as conftest.py::_sqlite_engine).
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "session_test.db"
        database_url = f"sqlite:///{db_path.as_posix()}"
        monkeypatch.setenv("PARO_DATABASE_URL", database_url)
        get_settings.cache_clear()
        session_module.get_engine.cache_clear()
        session_module.get_session_local.cache_clear()
        try:
            yield database_url
        finally:
            session_module.get_engine().dispose()
            session_module.get_session_local.cache_clear()
            session_module.get_engine.cache_clear()
            get_settings.cache_clear()


def test_get_engine_enables_sqlite_foreign_keys(_sqlite_url: str) -> None:
    engine = session_module.get_engine()
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_get_db_yields_working_session_against_real_engine(_sqlite_url: str) -> None:
    """First real exercise of api.deps.get_db(): today only the client
    fixture (which overrides it) and scripts/seed_demo.py's untested main()
    touch this path.
    """
    from paro.api.deps import get_db

    generator = get_db()
    session = next(generator)
    try:
        assert session.execute(text("SELECT 1")).scalar() == 1
    finally:
        generator.close()
