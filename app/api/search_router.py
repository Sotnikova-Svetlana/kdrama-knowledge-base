"""Маршруты REST API для интеллектуального нечёткого поиска и автоподсказок."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query

from app.schemas.kb_schemas import AutocompleteResponse, FuzzySearchResponse
from app.services.search_engine import get_search_engine

router = APIRouter(prefix="/search", tags=["Интеллектуальный поиск"])


@router.get("", response_model=FuzzySearchResponse)
def fuzzy_search(
    q: str = Query(..., min_length=1, max_length=150, description="Поисковый запрос"),
    limit: int = Query(default=24, ge=1, le=100),
    disable_layout_fix: bool = Query(default=False, description="Отключить автокоррекцию раскладки"),
) -> Dict[str, Any]:
    """Выполняет Fuzzy Search с исправлением опечаток и раскладки EN<->RU."""
    engine = get_search_engine()
    return engine.search(
        raw_query=q,
        limit=limit,
        record_telemetry=True,
        disable_layout_fix=disable_layout_fix,
    )


@router.get("/autocomplete", response_model=AutocompleteResponse)
def autocomplete_suggestions(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(default=10, ge=1, le=20),
) -> Dict[str, Any]:
    """Возвращает живые подсказки при вводе текста (дорамы, персоны, тропы)."""
    engine = get_search_engine()
    return engine.autocomplete(raw_query=q, limit=limit)
