"""Application configuration, read from environment variables.

All configuration comes from the environment (``PARO_`` prefix) and is
never hardcoded in the repository. ``.env.example`` documents the
variables; ``.env`` is gitignored.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    ``database_url`` defaults to a local SQLite file (``./paro.db``). This
    is a temporary pivot documented in
    ``docs/adr/0002-sqlite-temporary-due-to-virtualization-block.md``: the
    target is still PostgreSQL, and switching back is just a matter of
    changing this connection string.
    """

    model_config = SettingsConfigDict(
        env_prefix="PARO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "paro"
    env: str = "local"
    database_url: str = "sqlite:///./paro.db"
    default_timezone: str = "America/Monterrey"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns the cached settings.

    Cached so the environment isn't re-read on every request. Tests that
    need different values must call ``get_settings.cache_clear()``.
    """
    return Settings()
