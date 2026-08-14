"""FastAPI dependencies shared across routers."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from paro.db.session import get_session_local

__all__ = ["get_db"]


def get_db() -> Generator[Session]:
    """Opens one session per request and closes it at the end, no matter what.

    No commit of its own: each router owns its single ``commit()`` after a
    successful repository call (see ``paro.db.repositories``, which never
    commits). If the repository raises, the router lets the exception
    propagate without committing or manually rolling back; ``close()``
    safely discards the pending state.
    """
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()
