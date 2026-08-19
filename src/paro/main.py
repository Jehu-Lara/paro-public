"""PARO API entry point.

Sprint 3 adds the domain endpoints (``downtime-events``,
``production-records``, ``oee``) on top of Sprint 0's skeleton.
"""

import logging
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import RequestResponseEndpoint

from paro import __version__
from paro.api.errors import register_exception_handlers
from paro.api.rate_limit import limiter
from paro.api.routers.downtime import router as downtime_router
from paro.api.routers.oee import router as oee_router
from paro.api.routers.production import router as production_router
from paro.db.session import get_session_local
from paro.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PARO",
    version=__version__,
    summary="Downtime capture and deterministic OEE calculation for a production line.",
)


@app.middleware("http")
async def _log_requests(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Logs one structured line per request -- every request, including
    GET /health: nothing currently pings it on a schedule (no orchestrator,
    no configured uptime monitor -- the Render free tier only spins down
    from idling, per the README), so there's no polling noise to exclude
    yet, and a single uniform code path is simpler than a path exclusion.

    ``extra`` is a fixed allowlist only -- method/path/status_code/
    duration_ms/client host. Never request.headers, never Authorization or
    X-API-Key, never the Request object itself: those must never reach the
    log output, structured or not.
    """
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "client": request.client.host if request.client else None,
        },
    )
    return response


def _handle_rate_limit_exceeded(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RateLimitExceeded)
    return _rate_limit_exceeded_handler(request, exc)


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _handle_rate_limit_exceeded)

# GET-only: a cross-origin browser call to either POST endpoint always
# sends a JSON body, which is never a CORS "simple request" and therefore
# always triggers a preflight OPTIONS first. Restricting allow_methods to
# GET makes that preflight fail, so the browser never sends the actual
# POST -- without this having to touch the routers or the rate limiter.
# Non-browser callers (curl, Power BI, server-to-server) are unaffected:
# CORS is a browser-only restriction.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(downtime_router)
app.include_router(production_router)
app.include_router(oee_router)
register_exception_handlers(app)


@app.get("/health", tags=["ops"])
def health() -> dict[str, Any]:
    """Liveness of the application, plus a separate database reachability signal.

    Always returns 200 as long as the process is up, even when the
    database is unreachable: a failed ``SELECT 1`` is caught and reported
    via ``database`` instead of turning into a 500.
    """
    try:
        session = get_session_local()()
        try:
            session.execute(text("SELECT 1"))
            database_status = "ok"
        finally:
            session.close()
    except SQLAlchemyError:
        database_status = "unreachable"

    return {"status": "ok", "version": __version__, "database": database_status}
