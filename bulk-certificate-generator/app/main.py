"""FastAPI application factory and the default `app` instance used by Uvicorn."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api.routes import router
from app.config import Settings, get_settings
from app.database import create_db_engine, create_session_factory, init_db
from app.utils.file_utils import ensure_directory

logger = logging.getLogger(__name__)

WEB_UI_PATH = Path(__file__).resolve().parent / "static" / "index.html"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an app instance. Tests pass their own Settings (temp DB and folders)."""
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    engine = create_db_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_db(engine)
        ensure_directory(settings.certificate_output_dir)
        logger.info("Certificates will be stored in %s", settings.certificate_output_dir)
        yield
        engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "Submit a batch of recipients, generate one PDF certificate per recipient in the "
            "background, track progress, and download the generated certificates."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.include_router(router)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=settings.cors_allow_origin_regex,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Log the full traceback server-side; never leak it to the client.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    @app.get("/health", tags=["Health"], summary="Liveness check")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def web_ui() -> FileResponse:
        # Single-page UI served from the same origin as the API, so no CORS is needed.
        return FileResponse(WEB_UI_PATH, media_type="text/html")

    return app


app = create_app()
