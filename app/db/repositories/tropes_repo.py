"""Репозиторий для работы со справочниками сюжетных тропов, жанров и платформ."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.db.connection import DatabaseManager, get_db_manager


class TropesRepository:
    """Предоставляет таксономию сюжетных тропов, жанров и платформ БЗ."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or get_db_manager()

    def list_tropes(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Возвращает сюжетные тропы с количеством связанных дорам и средним весом."""
        where_sql = "WHERE t.category = ?" if category else ""
        params = [category] if category else []

        with self.db.read_session() as conn:
            rows = conn.execute(
                f"""
                SELECT t.*,
                       COUNT(dt.drama_id) AS dramas_count,
                       ROUND(COALESCE(AVG(dt.weight), t.base_weight), 3) AS avg_weight
                FROM tropes t
                LEFT JOIN drama_tropes dt ON dt.trope_id = t.id
                {where_sql}
                GROUP BY t.id
                ORDER BY dramas_count DESC, t.name_ru ASC
                """,
                params,
            ).fetchall()

            result: List[Dict[str, Any]] = []
            for r in rows:
                item = dict(r)
                try:
                    item["keywords"] = json.loads(item.get("keywords_json") or "[]")
                except json.JSONDecodeError:
                    item["keywords"] = []
                result.append(item)
            return result

    def list_genres(self) -> List[Dict[str, Any]]:
        """Возвращает жанры с подсчётом числа дорам."""
        with self.db.read_session() as conn:
            rows = conn.execute(
                """
                SELECT g.*, COUNT(dg.drama_id) AS dramas_count
                FROM genres g
                LEFT JOIN drama_genres dg ON dg.genre_id = g.id
                GROUP BY g.id
                ORDER BY dramas_count DESC, g.name_ru ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def list_platforms(self) -> List[Dict[str, Any]]:
        """Возвращает телеканалы и OTT-платформы с количеством дорам."""
        with self.db.read_session() as conn:
            rows = conn.execute(
                """
                SELECT p.*, COUNT(dp.drama_id) AS dramas_count
                FROM platforms p
                LEFT JOIN drama_platforms dp ON dp.platform_id = p.id
                GROUP BY p.id
                ORDER BY dramas_count DESC, p.name ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def list_years(self) -> List[Dict[str, Any]]:
        """Возвращает годы выхода дорам с количеством тайтлов в каталоге."""
        with self.db.read_session() as conn:
            rows = conn.execute(
                """
                SELECT release_year, COUNT(*) AS dramas_count
                FROM dramas
                GROUP BY release_year
                ORDER BY release_year DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

