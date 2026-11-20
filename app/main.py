"""Точка входа FastAPI приложения базы знаний по корейским дорамам."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging_config import configure_logging, get_logger
from app.db.connection import get_db_manager
from app.db.seed import seed_initial_database
from app.services.search_engine import get_search_engine
from app.services.sync_service import get_sync_orchestrator

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Управляет инициализацией БД, индекса поиска и планировщика APScheduler."""
    db = get_db_manager()
    db.initialize()
    seed_initial_database(db)
    get_search_engine().rebuild_index()

    orchestrator = get_sync_orchestrator()
    orchestrator.start_scheduler()
    logger.info("K-Drama Knowledge Base application started.")
    try:
        yield
    finally:
        orchestrator.stop_scheduler()
        logger.info("K-Drama Knowledge Base application stopped.")


def create_app() -> FastAPI:
    """Фабрика FastAPI-приложения."""
    settings = get_settings()
    settings.static_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title=settings.app_title,
        description=settings.app_description,
        version=settings.app_version,
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(api_router)

    # Статические файлы фронтенда (HTML5 / CSS3 / Vanilla JS)
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

    # Локальные сгенерированные постеры
    if settings.assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(settings.assets_dir)), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_spa() -> FileResponse:
        index_file = settings.static_dir / "index.html"
        return FileResponse(str(index_file))

    return app


app = create_app()
