"""Маршруты REST API и SSE для автономного обновления, статистики схемы и бенчмарков."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.db.repositories.sync_repo import SyncTelemetryRepository
from app.schemas.kb_schemas import BenchmarkSuiteResponse, SyncStatusResponse, SyncTriggerRequest
from app.services.benchmark_service import BenchmarkService
from app.services.sync_service import get_sync_orchestrator

router = APIRouter(tags=["Синхронизация, аналитика и эксперименты"])


@router.get("/health")
def health_check() -> Dict[str, str]:
    """Проверка готовности сервиса."""
    return {"status": "ok", "service": "kdrama-knowledge-base"}


@router.get("/overview")
def get_kb_overview() -> Dict[str, Any]:
    """Возвращает сводную статистику по 13 SQL-таблицам и телеметрии поиска."""
    return SyncTelemetryRepository().get_kb_overview()


@router.get("/sync/status", response_model=SyncStatusResponse)
def get_sync_status() -> Dict[str, Any]:
    """Возвращает статус планировщика APScheduler и журнал синхронизаций."""
    return get_sync_orchestrator().get_status()


@router.get("/sync/stream")
async def stream_manual_sync(
    mode: str = Query(default="auto", pattern="^(auto|tmdb|offline)$"),
) -> StreamingResponse:
    """Поток Server-Sent Events (SSE) для живого прогресс-бара и лога изменений при обновлении БЗ."""
    orchestrator = get_sync_orchestrator()

    async def event_generator() -> AsyncIterator[str]:
        async for evt in orchestrator.stream_sync(mode=mode, trigger_type="manual"):
            event_name = evt.get("event", "message")
            payload_json = json.dumps(evt.get("data", {}), ensure_ascii=False)
            yield f"event: {event_name}\ndata: {payload_json}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sync/run")
async def trigger_sync_once(payload: SyncTriggerRequest) -> Dict[str, Any]:
    """Выполняет синхронизацию в JSON-режиме (для программного вызова и тестов)."""
    orchestrator = get_sync_orchestrator()
    final_data: Dict[str, Any] = {}
    async for evt in orchestrator.stream_sync(mode=payload.mode, trigger_type="manual"):
        if evt.get("event") in ("complete", "error"):
            final_data = evt.get("data", {})
    return final_data


@router.get("/benchmark", response_model=BenchmarkSuiteResponse)
def run_benchmark_suite() -> Dict[str, Any]:
    """Запускает набор экспериментов по оценке качества Fuzzy Search и рекомендаций."""
    return BenchmarkService().run_full_benchmark()
