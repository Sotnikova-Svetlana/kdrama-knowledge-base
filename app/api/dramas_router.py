"""Маршруты REST API для каталога дорам, персон, жанров, тропов и рекомендаций."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from app.db.repositories.dramas_repo import DramasRepository
from app.db.repositories.persons_repo import PersonsRepository
from app.db.repositories.tropes_repo import TropesRepository
from app.schemas.kb_schemas import (
    DramaCreateRequest,
    DramaDetail,
    DramaListResponse,
    RecommendationsResponse,
)
from app.services.recommender import RecommenderService
from app.services.search_engine import get_search_engine

router = APIRouter(tags=["Каталог и сущности БЗ"])


@router.get("/dramas", response_model=DramaListResponse)
def list_dramas(
    genre: Optional[str] = Query(default=None, description="Slug жанра"),
    trope: Optional[str] = Query(default=None, description="Slug сюжетного тропа"),
    platform: Optional[str] = Query(default=None, description="Slug платформы/канала"),
    status: Optional[str] = Query(default=None, description="Статус выхода"),
    year: Optional[int] = Query(default=None, ge=1980, le=2035, description="Точный год выхода"),
    year_from: Optional[int] = Query(default=None, ge=1980, le=2035),
    year_to: Optional[int] = Query(default=None, ge=1980, le=2035),
    sort_by: str = Query(default="rating", pattern="^(rating|year|popularity|title|updated)$"),
    limit: int = Query(default=48, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    """Возвращает каталог дорам с фасетной фильтрацией по таксономии БЗ."""
    repo = DramasRepository()
    effective_from = year if year is not None else year_from
    effective_to = year if year is not None else year_to
    items, total = repo.list_dramas(
        genre_slug=genre,
        trope_slug=trope,
        platform_slug=platform,
        status=status,
        year_from=effective_from,
        year_to=effective_to,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/dramas", response_model=DramaDetail, status_code=201)
def create_drama(payload: DramaCreateRequest) -> Dict[str, Any]:
    """Добавляет или обновляет дораму в базе знаний и переиндексирует поиск."""
    repo = DramasRepository()
    created = repo.create_or_update_manual_drama(payload.model_dump())
    get_search_engine().rebuild_index()
    return created


@router.get("/dramas/{drama_id}", response_model=DramaDetail)
def get_drama(drama_id: int) -> Dict[str, Any]:
    """Возвращает детальную карточку дорамы со всеми связями."""
    return DramasRepository().get_drama_by_id(drama_id)


@router.get("/dramas/{drama_id}/recommendations", response_model=RecommendationsResponse)
def get_drama_recommendations(
    drama_id: int,
    limit: int = Query(default=6, ge=1, le=20),
) -> Dict[str, Any]:
    """Возвращает похожие дорамы с объяснением пересечения тропов, жанров и актёров."""
    return RecommenderService().get_similar_dramas(drama_id=drama_id, limit=limit)


@router.get("/genres")
def list_genres() -> List[Dict[str, Any]]:
    """Возвращает справочник жанров с количеством дорам."""
    return TropesRepository().list_genres()


@router.get("/platforms")
def list_platforms() -> List[Dict[str, Any]]:
    """Возвращает справочник телеканалов и платформ."""
    return TropesRepository().list_platforms()


@router.get("/tropes")
def list_tropes(category: Optional[str] = Query(default=None)) -> List[Dict[str, Any]]:
    """Возвращает таксономию сюжетных тропов с ключевыми словами и весами."""
    return TropesRepository().list_tropes(category=category)


@router.get("/years")
def list_years() -> List[Dict[str, Any]]:
    """Возвращает список доступных годов выхода дорам и их количество."""
    return TropesRepository().list_years()


@router.get("/persons")
def list_persons(
    profession: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
) -> List[Dict[str, Any]]:
    """Возвращает список актёров, режиссёров и сценаристов."""
    return PersonsRepository().list_persons(profession=profession, query=q, limit=limit)


@router.get("/persons/{person_id}")
def get_person(person_id: int) -> Dict[str, Any]:
    """Возвращает профиль персоны и её фильмографию в БЗ."""
    return PersonsRepository().get_person_detail(person_id)
