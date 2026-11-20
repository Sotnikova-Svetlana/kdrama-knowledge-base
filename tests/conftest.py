"""Фикстуры pytest для изолированного тестирования БЗ и FastAPI API."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from app.db.connection import DatabaseManager, set_db_manager
from app.db.seed import seed_initial_database
from app.main import create_app
from app.services import search_engine as search_module
from app.services import sync_service as sync_module


@pytest.fixture()
def isolated_client(tmp_path: Path) -> Iterator[TestClient]:
    """Изолированный экземпляр БД SQLite и TestClient FastAPI для каждого теста."""
    db_file = tmp_path / "test_kdrama_kb.db"
    manager = DatabaseManager(db_path=db_file)
    manager.initialize()
    set_db_manager(manager)
    seed_initial_database(manager, force=True)

    # Сбрасываем синглтоны сервисов на тестовую БД
    search_module._search_engine = None
    sync_module._sync_orchestrator = None

    app = create_app()
    with TestClient(app) as client:
        yield client

    search_module._search_engine = None
    sync_module._sync_orchestrator = None
