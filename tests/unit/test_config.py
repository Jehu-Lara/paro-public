"""Pruebas de la configuracion por entorno."""

import pytest

from paro.config import Settings, get_settings


def test_settings_read_prefixed_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARO_ENV", "ci")
    monkeypatch.setenv("PARO_DEFAULT_TIMEZONE", "UTC")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.env == "ci"
    assert settings.default_timezone == "UTC"


def test_database_url_is_optional_in_sprint_0() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.database_url is None or isinstance(settings.database_url, str)


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()

    assert get_settings() is get_settings()
