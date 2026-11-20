"""Репозиторий для работы с дорамами и их семантическими связями."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from app.core.exceptions import EntityNotFoundError
from app.db.connection import DatabaseManager, get_db_manager
from app.db.seed import compute_drama_hash, slugify_text


class DramasRepository:
    """Инкапсулирует SQL-запросы к таблицам dramas, drama_genres, drama_tropes, drama_platforms и cast_roles."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or get_db_manager()

    def list_dramas(
        self,
        genre_slug: Optional[str] = None,
        trope_slug: Optional[str] = None,
        platform_slug: Optional[str] = None,
        status: Optional[str] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        sort_by: str = "rating",
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Возвращает отфильтрованный список карточек дорам и общее количество."""
        where_clauses: List[str] = ["1=1"]
        params: List[Any] = []

        if genre_slug:
            where_clauses.append(
                "EXISTS (SELECT 1 FROM drama_genres dg JOIN genres g ON g.id = dg.genre_id "
                "WHERE dg.drama_id = d.id AND g.slug = ?)"
            )
            params.append(genre_slug)

        if trope_slug:
            where_clauses.append(
                "EXISTS (SELECT 1 FROM drama_tropes dt JOIN tropes t ON t.id = dt.trope_id "
                "WHERE dt.drama_id = d.id AND t.slug = ?)"
            )
            params.append(trope_slug)

        if platform_slug:
            where_clauses.append(
                "EXISTS (SELECT 1 FROM drama_platforms dp JOIN platforms p ON p.id = dp.platform_id "
                "WHERE dp.drama_id = d.id AND p.slug = ?)"
            )
            params.append(platform_slug)

        if status:
            where_clauses.append("d.status = ?")
            params.append(status)

        if year_from is not None:
            where_clauses.append("d.release_year >= ?")
            params.append(year_from)

        if year_to is not None:
            where_clauses.append("d.release_year <= ?")
            params.append(year_to)

        sort_map = {
            "rating": "d.rating DESC, d.votes_count DESC",
            "year": "d.release_year DESC, d.rating DESC",
            "popularity": "d.popularity_score DESC, d.rating DESC",
            "title": "d.title_ru ASC",
            "updated": "d.updated_at DESC, d.id DESC",
        }
        order_sql = sort_map.get(sort_by, sort_map["rating"])
        where_sql = " AND ".join(where_clauses)

        with self.db.read_session() as conn:
            count_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM dramas d WHERE {where_sql}",
                params,
            ).fetchone()
            total = int(count_row["cnt"]) if count_row else 0

            rows = conn.execute(
                f"""
                SELECT d.*
                FROM dramas d
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()

            dramas = [self._hydrate_summary(conn, dict(row)) for row in rows]
            return dramas, total

    def get_drama_by_id(self, drama_id: int) -> Dict[str, Any]:
        """Возвращает полную карточку дорамы с тропами, актёрами, жанрами, платформами и списками."""
        with self.db.read_session() as conn:
            row = conn.execute("SELECT * FROM dramas WHERE id = ?", (drama_id,)).fetchone()
            if not row:
                raise EntityNotFoundError("Дорама", drama_id)
            return self._hydrate_detail(conn, dict(row))

    def get_drama_by_slug(self, slug: str) -> Dict[str, Any]:
        """Возвращает полную карточку дорамы по slug."""
        with self.db.read_session() as conn:
            row = conn.execute("SELECT * FROM dramas WHERE slug = ?", (slug,)).fetchone()
            if not row:
                raise EntityNotFoundError("Дорама", slug)
            return self._hydrate_detail(conn, dict(row))

    def get_dramas_by_ids(self, drama_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """Пакетно загружает сводные карточки дорам по списку ID."""
        if not drama_ids:
            return {}
        placeholders = ",".join("?" for _ in drama_ids)
        with self.db.read_session() as conn:
            rows = conn.execute(
                f"SELECT * FROM dramas WHERE id IN ({placeholders})",
                drama_ids,
            ).fetchall()
            return {int(row["id"]): self._hydrate_summary(conn, dict(row)) for row in rows}

    def get_all_feature_vectors(self) -> List[Dict[str, Any]]:
        """Загружает компактные семантические векторы всех дорам для рекомендаций и поиска."""
        with self.db.read_session() as conn:
            dramas = [dict(r) for r in conn.execute("SELECT * FROM dramas ORDER BY id").fetchall()]

            genre_rows = conn.execute(
                """
                SELECT dg.drama_id, g.id AS genre_id, g.slug, g.name_ru
                FROM drama_genres dg
                JOIN genres g ON g.id = dg.genre_id
                """
            ).fetchall()

            trope_rows = conn.execute(
                """
                SELECT dt.drama_id, t.id AS trope_id, t.slug, t.name_ru, t.category, dt.weight
                FROM drama_tropes dt
                JOIN tropes t ON t.id = dt.trope_id
                """
            ).fetchall()

            cast_rows = conn.execute(
                """
                SELECT cr.drama_id, p.id AS person_id, p.slug, p.name_ru, p.name_en,
                       cr.role_type, cr.character_name, cr.billing_order
                FROM cast_roles cr
                JOIN persons p ON p.id = cr.person_id
                """
            ).fetchall()

            platform_rows = conn.execute(
                """
                SELECT dp.drama_id, p.slug, p.name
                FROM drama_platforms dp
                JOIN platforms p ON p.id = dp.platform_id
                """
            ).fetchall()

        genres_by_d: Dict[int, List[Dict[str, Any]]] = {}
        for r in genre_rows:
            genres_by_d.setdefault(int(r["drama_id"]), []).append(dict(r))

        tropes_by_d: Dict[int, List[Dict[str, Any]]] = {}
        for r in trope_rows:
            tropes_by_d.setdefault(int(r["drama_id"]), []).append(dict(r))

        cast_by_d: Dict[int, List[Dict[str, Any]]] = {}
        for r in cast_rows:
            cast_by_d.setdefault(int(r["drama_id"]), []).append(dict(r))

        platforms_by_d: Dict[int, List[Dict[str, Any]]] = {}
        for r in platform_rows:
            platforms_by_d.setdefault(int(r["drama_id"]), []).append(dict(r))

        for d in dramas:
            did = int(d["id"])
            d["genres"] = genres_by_d.get(did, [])
            d["tropes"] = sorted(
                tropes_by_d.get(did, []),
                key=lambda item: float(item["weight"]),
                reverse=True,
            )
            d["cast"] = sorted(
                cast_by_d.get(did, []),
                key=lambda item: int(item["billing_order"]),
            )
            d["platforms"] = platforms_by_d.get(did, [])
        return dramas

    def create_or_update_manual_drama(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Создаёт или обновляет дораму вручную через REST API."""
        slug = payload.get("slug") or slugify_text(payload["title_en"] or payload["title_ru"])
        content_hash = compute_drama_hash(payload)

        with self.db.write_session() as conn:
            conn.execute(
                """
                INSERT INTO dramas (
                    slug, title_ru, title_en, title_kr, title_romaja,
                    synopsis_ru, release_year, episodes_count, status,
                    rating, poster_url, content_hash, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(slug) DO UPDATE SET
                    title_ru = excluded.title_ru,
                    title_en = excluded.title_en,
                    title_kr = excluded.title_kr,
                    title_romaja = excluded.title_romaja,
                    synopsis_ru = excluded.synopsis_ru,
                    release_year = excluded.release_year,
                    episodes_count = excluded.episodes_count,
                    status = excluded.status,
                    rating = excluded.rating,
                    poster_url = CASE WHEN excluded.poster_url != '' THEN excluded.poster_url ELSE dramas.poster_url END,
                    content_hash = excluded.content_hash,
                    updated_at = datetime('now')
                """,
                (
                    slug,
                    payload["title_ru"],
                    payload["title_en"],
                    payload.get("title_kr", ""),
                    payload.get("title_romaja", ""),
                    payload.get("synopsis_ru", ""),
                    int(payload["release_year"]),
                    int(payload.get("episodes_count", 16)),
                    payload.get("status", "Completed"),
                    float(payload.get("rating", 8.0)),
                    payload.get("poster_url", ""),
                    content_hash,
                ),
            )
            row = conn.execute("SELECT id FROM dramas WHERE slug = ?", (slug,)).fetchone()
            drama_id = int(row["id"])

            for g_slug in payload.get("genre_slugs", []):
                g_row = conn.execute("SELECT id FROM genres WHERE slug = ?", (g_slug,)).fetchone()
                if g_row:
                    conn.execute(
                        "INSERT INTO drama_genres (drama_id, genre_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                        (drama_id, int(g_row["id"])),
                    )

            for t_slug in payload.get("trope_slugs", []):
                t_row = conn.execute("SELECT id, base_weight FROM tropes WHERE slug = ?", (t_slug,)).fetchone()
                if t_row:
                    conn.execute(
                        """
                        INSERT INTO drama_tropes (drama_id, trope_id, weight, source)
                        VALUES (?, ?, ?, 'manual')
                        ON CONFLICT(drama_id, trope_id) DO NOTHING
                        """,
                        (drama_id, int(t_row["id"]), float(t_row["base_weight"])),
                    )

        return self.get_drama_by_id(drama_id)

    def _hydrate_summary(self, conn: sqlite3.Connection, drama: Dict[str, Any]) -> Dict[str, Any]:
        """Дополняет строку дорамы жанрами, платформами и топ-3 тропами для карточки каталога."""
        did = int(drama["id"])
        genres = conn.execute(
            """
            SELECT g.id, g.slug, g.name_ru, g.name_en
            FROM drama_genres dg
            JOIN genres g ON g.id = dg.genre_id
            WHERE dg.drama_id = ?
            ORDER BY g.name_ru
            """,
            (did,),
        ).fetchall()

        platforms = conn.execute(
            """
            SELECT p.id, p.slug, p.name, p.platform_type, dp.is_original
            FROM drama_platforms dp
            JOIN platforms p ON p.id = dp.platform_id
            WHERE dp.drama_id = ?
            ORDER BY dp.is_original DESC, p.name
            """,
            (did,),
        ).fetchall()

        tropes = conn.execute(
            """
            SELECT t.id, t.slug, t.name_ru, t.category, dt.weight, dt.source
            FROM drama_tropes dt
            JOIN tropes t ON t.id = dt.trope_id
            WHERE dt.drama_id = ?
            ORDER BY dt.weight DESC, t.name_ru
            """,
            (did,),
        ).fetchall()

        list_rows = conn.execute(
            """
            SELECT ul.slug, ul.name
            FROM user_list_items uli
            JOIN user_lists ul ON ul.id = uli.list_id
            WHERE uli.drama_id = ?
            """,
            (did,),
        ).fetchall()

        drama["genres"] = [dict(r) for r in genres]
        drama["platforms"] = [dict(r) for r in platforms]
        drama["tropes"] = [dict(r) for r in tropes]
        drama["in_lists"] = [dict(r) for r in list_rows]
        return drama

    def _hydrate_detail(self, conn: sqlite3.Connection, drama: Dict[str, Any]) -> Dict[str, Any]:
        """Дополняет карточку дорамы полным актёрским составом и пользовательскими отметками."""
        hydrated = self._hydrate_summary(conn, drama)
        did = int(drama["id"])

        cast = conn.execute(
            """
            SELECT p.id, p.slug, p.name_ru, p.name_en, p.name_kr,
                   p.primary_profession, p.photo_url, cr.role_type, cr.character_name, cr.billing_order
            FROM cast_roles cr
            JOIN persons p ON p.id = cr.person_id
            WHERE cr.drama_id = ?
            ORDER BY
                CASE cr.role_type
                    WHEN 'Main' THEN 1
                    WHEN 'Support' THEN 2
                    WHEN 'Director' THEN 3
                    WHEN 'Writer' THEN 4
                    ELSE 5
                END,
                cr.billing_order ASC
            """,
            (did,),
        ).fetchall()

        list_items = conn.execute(
            """
            SELECT uli.id AS item_id, ul.id AS list_id, ul.slug AS list_slug, ul.name AS list_name,
                   uli.personal_rating, uli.watched_episodes, uli.notes
            FROM user_list_items uli
            JOIN user_lists ul ON ul.id = uli.list_id
            WHERE uli.drama_id = ?
            """,
            (did,),
        ).fetchall()

        hydrated["cast"] = [dict(r) for r in cast]
        hydrated["user_entries"] = [dict(r) for r in list_items]
        return hydrated
