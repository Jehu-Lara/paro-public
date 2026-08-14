"""Configuracion de la aplicacion, leida de variables de entorno.

Toda la configuracion entra por el entorno (prefijo ``PARO_``) y nunca se
codifica en el repositorio. ``.env.example`` documenta las variables; ``.env``
esta ignorado por Git.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes de la aplicacion.

    ``database_url`` por defecto apunta a un archivo SQLite local
    (``./paro.db``). Es un pivote temporal documentado en
    ``docs/adr/0002-sqlite-temporal-por-bloqueo-de-virtualizacion.md``: el
    destino sigue siendo PostgreSQL, y basta con cambiar esta cadena de
    conexion para volver a el.
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
    """Devuelve los ajustes en cache.

    Se cachea para no releer el entorno en cada request. Los tests que
    necesiten otros valores deben llamar a ``get_settings.cache_clear()``.
    """
    return Settings()
