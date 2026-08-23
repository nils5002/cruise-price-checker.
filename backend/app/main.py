"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import router
from app.config import settings
from app.core.logging_setup import get_logger, setup_logging
from app.core.security import UrlValidationError
from app.db import init_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("%s %s startet (Umgebung: %s)", settings.app_name, __version__, settings.environment)
    init_db()
    from app.scheduler.service import start_scheduler, stop_scheduler

    try:
        start_scheduler()
    except Exception:  # noqa: BLE001 - Nebenfunktion darf den Start nie stoppen
        logger.exception("Scheduler-Start fehlgeschlagen; Anwendung läuft ohne automatische Checks.")
    try:
        yield
    finally:
        stop_scheduler()
        from app.scanner.queue import queue

        queue.shutdown()
        logger.info("Anwendung beendet.")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Vergleicht Preise derselben Kreuzfahrt unter verschiedenen, möglichst "
            "neutralen Browserbedingungen. Keine Umgehung von Bot-Schutz, keine Buchungen."
        ),
        root_path=settings.root_path or "",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(UrlValidationError)
    async def _url_error(_request: Request, exc: UrlValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # Health endpoints: /health (docker healthcheck) and /api/health.
    @app.get("/health", tags=["system"])
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(router, prefix="/api")
    return app


app = create_app()
