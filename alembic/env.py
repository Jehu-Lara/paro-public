"""Entorno de Alembic: la URL y los metadatos vienen de la aplicacion.

Importa explicitamente todos los modelos antes de fijar ``target_metadata``:
si ``Base.metadata`` no los ha visto, ``autogenerate`` produce una migracion
vacia sin avisar de ningun error.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from paro.config import get_settings
from paro.db.base import Base
from paro.db.models import (  # noqa: F401  (registran las tablas en Base.metadata)
    DowntimeEvent,
    DowntimeReason,
    Machine,
    ProductionLine,
    ProductionRecord,
    Shift,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Genera SQL sin abrir conexion, usando la URL como contexto literal."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Aplica migraciones con una conexion real a la base configurada."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    is_sqlite = connectable.dialect.name == "sqlite"

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
