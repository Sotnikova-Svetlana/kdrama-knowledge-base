"""Настройка структурированного логирования для модулей БЗ."""

from __future__ import annotations

import logging
import sys
from typing import Optional


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Инициализирует единый формат логов приложения и сторонних библиотек."""
    root_logger = logging.getLogger("kdrama_kb")
    if root_logger.handlers:
        return root_logger

    root_logger.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    # Приглушаем избыточный вывод сетевых клиентов
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)

    return root_logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Возвращает дочерний логгер в пространстве имён kdrama_kb."""
    configure_logging()
    if not name:
        return logging.getLogger("kdrama_kb")
    clean_name = name.replace("app.", "")
    return logging.getLogger(f"kdrama_kb.{clean_name}")
