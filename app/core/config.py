"""Конфигурация приложения K-Drama Knowledge Base.

Загружает параметры из переменных окружения и файла .env,
предоставляет единую точку доступа к путям БД, настройкам TMDB API,
параметрам планировщика APScheduler и весовым коэффициентам алгоритмов.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Глобальные настройки базы знаний."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Основные параметры сервиса
    app_title: str = "K-Drama Knowledge Base"
    app_description: str = (
        "Интеллектуальная база знаний по корейским дорамам: "
        "реляционная модель БЗ, нечёткий поиск с коррекцией раскладки, "
        "автономное обновление из TMDB/JSON, рекомендации и граф связей."
    )
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # База данных
    database_path: str = Field(
        default="data/kdrama_kb.db",
        description="Относительный или абсолютный путь к файлу SQLite",
    )
    db_engine: Literal["sqlite", "postgresql"] = "sqlite"

    # Внешний API TMDB и автономная синхронизация
    tmdb_api_key: str = Field(default="", description="Ключ доступа TMDB API v3")
    tmdb_base_url: str = "https://api.themoviedb.org/3"
    tmdb_image_base_url: str = "https://image.tmdb.org/t/p/w500"
    tmdb_language: str = "ru-RU"
    tmdb_timeout_seconds: float = 10.0

    # Планировщик APScheduler
    sync_enabled: bool = True
    sync_interval_hours: int = Field(default=6, ge=1, le=168)
    sync_offline_fallback: bool = True

    # Параметры Fuzzy Search
    fuzzy_min_score: float = Field(default=58.0, ge=0.0, le=100.0)
    fuzzy_correction_threshold: float = Field(default=84.0, ge=0.0, le=100.0)
    autocomplete_limit: int = Field(default=10, ge=1, le=30)

    # Весовые коэффициенты рекомендательного алгоритма (сумма = 1.0)
    rec_weight_tropes: float = 0.50
    rec_weight_genres: float = 0.25
    rec_weight_cast: float = 0.20
    rec_weight_meta: float = 0.05

    @property
    def resolved_db_path(self) -> Path:
        """Возвращает абсолютный путь к файлу SQLite и гарантирует наличие папки."""
        path = Path(self.database_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def data_dir(self) -> Path:
        """Каталог со встроенными JSON-датасетами БЗ."""
        return BASE_DIR / "app" / "data"

    @property
    def static_dir(self) -> Path:
        """Каталог статических файлов фронтенда (HTML5/CSS3/Vanilla JS)."""
        return BASE_DIR / "app" / "static"

    @property
    def assets_dir(self) -> Path:
        """Каталог сгенерированных медиа-ассетов (постеры)."""
        return BASE_DIR / "src" / "assets"

    @property
    def offline_dataset_path(self) -> Path:
        """Путь к базовому оффлайн-датасету дорам."""
        return self.data_dir / "offline_dataset.json"

    @property
    def sync_delta_path(self) -> Path:
        """Путь к резервному дельта-пакету обновлений."""
        return self.data_dir / "sync_delta_batch.json"

    @property
    def has_tmdb_key(self) -> bool:
        """Проверяет, задан ли непустой ключ TMDB API."""
        return bool(self.tmdb_api_key and self.tmdb_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает кэшированный экземпляр конфигурации."""
    return Settings()
