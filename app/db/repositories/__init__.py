"""Репозиторный слой доступа к таблицам базы знаний."""

from app.db.repositories.dramas_repo import DramasRepository
from app.db.repositories.lists_repo import ListsRepository
from app.db.repositories.persons_repo import PersonsRepository
from app.db.repositories.sync_repo import SyncTelemetryRepository
from app.db.repositories.tropes_repo import TropesRepository

__all__ = [
    "DramasRepository",
    "PersonsRepository",
    "TropesRepository",
    "ListsRepository",
    "SyncTelemetryRepository",
]
