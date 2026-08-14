"""PARO API entry point.

Sprint 3 adds the domain endpoints (``downtime-events``,
``production-records``, ``oee``) on top of Sprint 0's skeleton. The
database check in ``/health`` is still pending a later sprint.
"""

from typing import Any

from fastapi import FastAPI

from paro import __version__
from paro.api.errors import register_exception_handlers
from paro.api.routers.downtime import router as downtime_router
from paro.api.routers.oee import router as oee_router
from paro.api.routers.production import router as production_router

app = FastAPI(
    title="PARO",
    version=__version__,
    summary="Downtime capture and deterministic OEE calculation for a production line.",
)

app.include_router(downtime_router)
app.include_router(production_router)
app.include_router(oee_router)
register_exception_handlers(app)


@app.get("/health", tags=["ops"])
def health() -> dict[str, Any]:
    """Liveness of the application.

    Still does not query the database, even though the persistence layer
    exists since S2a: the dependency check is deferred to a later sprint.
    """
    return {"status": "ok", "version": __version__}
