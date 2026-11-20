"""Маршруты REST API для графа семантических связей и пользовательских списков."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Response

from app.db.repositories.lists_repo import ListsRepository
from app.schemas.kb_schemas import (
    KnowledgeGraphResponse,
    UserListCreateRequest,
    UserListItemUpsertRequest,
)
from app.services.graph_builder import KnowledgeGraphBuilder

router = APIRouter(tags=["Граф связей и списки"])


@router.get("/graph", response_model=KnowledgeGraphResponse)
def get_knowledge_graph(
    center_type: str = Query(default="drama", pattern="^(drama|person|trope)$"),
    center_id: Optional[int] = Query(default=None),
    depth: int = Query(default=1, ge=1, le=2),
    include_cast: bool = Query(default=True),
    include_tropes: bool = Query(default=True),
    include_genres: bool = Query(default=True),
) -> Dict[str, Any]:
    """Строит интерактивный подграф семантической сети БЗ."""
    return KnowledgeGraphBuilder().build_subgraph(
        center_type=center_type,
        center_id=center_id,
        depth=depth,
        include_cast=include_cast,
        include_tropes=include_tropes,
        include_genres=include_genres,
    )


@router.get("/lists")
def get_user_lists() -> List[Dict[str, Any]]:
    """Возвращает все пользовательские списки вместе с добавленными дорамами."""
    return ListsRepository().get_all_lists()


@router.post("/lists", status_code=201)
def create_user_list(payload: UserListCreateRequest) -> Dict[str, Any]:
    """Создаёт пользовательскую подборку дорам."""
    return ListsRepository().create_custom_list(
        name=payload.name,
        description=payload.description,
    )


@router.delete("/lists/{list_id}", status_code=204)
def delete_user_list(list_id: int) -> Response:
    """Удаляет пользовательский список."""
    ListsRepository().delete_custom_list(list_id)
    return Response(status_code=204)


@router.put("/lists/{list_id}/items")
def upsert_user_list_item(list_id: int, payload: UserListItemUpsertRequest) -> Dict[str, Any]:
    """Добавляет дораму в список или обновляет прогресс просмотра и оценку."""
    return ListsRepository().upsert_list_item(
        list_id=list_id,
        drama_id=payload.drama_id,
        personal_rating=payload.personal_rating,
        watched_episodes=payload.watched_episodes,
        notes=payload.notes,
    )


@router.delete("/lists/{list_id}/items/{drama_id}", status_code=204)
def remove_user_list_item(list_id: int, drama_id: int) -> Response:
    """Удаляет дораму из пользовательского списка."""
    ListsRepository().remove_list_item(list_id=list_id, drama_id=drama_id)
    return Response(status_code=204)
