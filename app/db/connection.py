"""Менеджер подключений к реляционной базе знаний (SQLite / PostgreSQL-ready)."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.db.schema import init_schema

logger = get_logger(__name__)


class DatabaseManager:
    """Управляет подключениями, WAL-режимом, транзакциями и блокировками записи."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        settings = get_settings()
        self.db_path = db_path or settings.resolved_db_path
        self._write_lock = threading.RLock()
        self._initialized = False

    def create_connection(self) -> sqlite3.Connection:
        """Создаёт новое соединение SQLite с включёнными внешними ключами и Row-фабрикой."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        return conn

    def initialize(self) -> None:
        """Гарантирует существование всех 13 таблиц и индексов."""
        with self._write_lock:
            conn = self.create_connection()
            try:
                init_schema(conn)
                self._initialized = True
                logger.info("SQLite schema initialized at %s", self.db_path)
            finally:
                conn.close()

    @contextmanager
    def read_session(self) -> Iterator[sqlite3.Connection]:
        """Контекстный менеджер для операций чтения."""
        if not self._initialized:
            self.initialize()
        conn = self.create_connection()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def write_session(self) -> Iterator[sqlite3.Connection]:
        """Потокобезопасный контекстный менеджер с атомарным commit/rollback."""
        if not self._initialized:
            self.initialize()
        with self._write_lock:
            conn = self.create_connection()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()


_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """Возвращает синглтон-менеджер БД."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
        _db_manager.initialize()
    return _db_manager


def set_db_manager(manager: DatabaseManager) -> None:
    """Позволяет подменить менеджер БД (например, в изолированных тестах)."""
    global _db_manager
    _db_manager = manager
