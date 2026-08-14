"""Dependencias de FastAPI compartidas entre routers."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from paro.db.session import get_session_local

__all__ = ["get_db"]


def get_db() -> Generator[Session]:
    """Abre una sesion por request y la cierra al final, pase lo que pase.

    Sin commit propio: cada router es dueno de su unico ``commit()`` tras una
    llamada exitosa al repositorio (ver ``paro.db.repositories``, que nunca
    comitea). Si el repositorio lanza, el router deja propagar la excepcion
    sin comitear ni hacer rollback manual; ``close()`` descarta el estado
    pendiente de forma segura.
    """
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()
