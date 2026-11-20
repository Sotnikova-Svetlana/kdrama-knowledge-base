"""Иерархия доменных исключений и обработчики ошибок FastAPI."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class KnowledgeBaseError(Exception):
    """Базовое исключение бизнес-логики базы знаний."""

    def __init__(self, message: str, status_code: int = 500, code: str = "kb_error") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class EntityNotFoundError(KnowledgeBaseError):
    """Исключение при отсутствии запрошенной сущности в БЗ."""

    def __init__(self, entity: str, identifier: object) -> None:
        super().__init__(
            message=f"Сущность «{entity}» с идентификатором {identifier} не найдена в базе знаний.",
            status_code=404,
            code="entity_not_found",
        )


class ValidationConflictError(KnowledgeBaseError):
    """Конфликт бизнес-правил или некорректные параметры запроса."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, status_code=400, code="validation_conflict")


class SyncSourceError(KnowledgeBaseError):
    """Ошибка взаимодействия с внешним или резервным источником синхронизации."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, status_code=502, code="sync_source_error")


def register_exception_handlers(app: FastAPI) -> None:
    """Регистрирует централизованные JSON-обработчики исключений в FastAPI."""

    @app.exception_handler(KnowledgeBaseError)
    async def kb_error_handler(_request: Request, exc: KnowledgeBaseError) -> JSONResponse:
        logger.warning("Domain error [%s]: %s", exc.code, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.code,
                "detail": exc.message,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "detail": "Внутренняя ошибка сервера при обработке запроса к базе знаний.",
            },
        )
