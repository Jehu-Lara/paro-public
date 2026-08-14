"""Punto de entrada de la API de PARO.

Sprint 3 agrega los endpoints de dominio (``downtime-events``,
``production-records``, ``oee``) sobre el esqueleto de Sprint 0. El chequeo
de base de datos en ``/health`` sigue pendiente de un sprint posterior.
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
    summary="Captura de paros de linea y calculo determinista de OEE.",
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
