"""Пакет REST API роутеров FastAPI."""

from fastapi import APIRouter

from app.api.dramas_router import router as dramas_router
from app.api.knowledge_router import router as knowledge_router
from app.api.search_router import router as search_router
from app.api.sync_router import router as sync_router

api_router = APIRouter(prefix="/api")
api_router.include_router(dramas_router)
api_router.include_router(search_router)
api_router.include_router(knowledge_router)
api_router.include_router(sync_router)

__all__ = ["api_router"]
