"""Начальное заполнение базы знаний из встроенного оффлайн-корпуса JSON."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.db.connection import DatabaseManager, get_db_manager

logger = get_logger(__name__)


DEFAULT_USER_LISTS = [
    {
        "slug": "watching",
        "name": "Смотрю сейчас",
        "list_type": "watching",
        "description": "Дорамы в активном процессе просмотра",
        "is_system": 1,
    },
    {
        "slug": "planned",
        "name": "В планах",
        "list_type": "planned",
        "description": "Очередь дорам к просмотру",
        "is_system": 1,
    },
    {
        "slug": "completed",
        "name": "Просмотрено",
        "list_type": "completed",
        "description": "Завершённые тайтлы с личной оценкой",
        "is_system": 1,
    },
    {
        "slug": "favorites",
        "name": "Избранное",
        "list_type": "favorites",
        "description": "Любимые дорамы и эталонные сюжеты",
        "is_system": 1,
    },
]


def slugify_text(text: str) -> str:
    """Генерирует стабильный URL-безопасный slug из строки."""
    normalized = text.lower().strip()
    normalized = re.sub(r"[^a-z0-9а-яё\-]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or hashlib.md5(text.encode("utf-8")).hexdigest()[:10]


def compute_drama_hash(item: Dict[str, Any]) -> str:
    """Вычисляет детерминированный хеш содержимого записи дорамы для отслеживания изменений."""
    payload = "|".join(
        [
            str(item.get("title_ru", "")),
            str(item.get("title_en", "")),
            str(item.get("status", "")),
            str(item.get("episodes_count", "")),
            str(round(float(item.get("rating", 0.0)), 2)),
            str(item.get("poster_url", ""))[:80],
            str(item.get("synopsis_ru", ""))[:160],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def seed_default_lists(conn: sqlite3.Connection) -> None:
    """Создаёт системные пользовательские списки, если они отсутствуют."""
    for lst in DEFAULT_USER_LISTS:
        conn.execute(
            """
            INSERT INTO user_lists (slug, name, list_type, description, is_system)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO NOTHING
            """,
            (lst["slug"], lst["name"], lst["list_type"], lst["description"], lst["is_system"]),
        )


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[а-яА-ЯёЁ]", text or ""))


def upsert_reference_dictionaries(
    conn: sqlite3.Connection,
    dataset: Dict[str, Any],
) -> Dict[str, Dict[str, int]]:
    """Загружает справочники жанров, платформ, тропов и персон; возвращает карты slug -> id."""
    genre_map: Dict[str, int] = {}
    for g in dataset.get("genres", []):
        slug = g["slug"]
        conn.execute(
            """
            INSERT INTO genres (tmdb_genre_id, slug, name_ru, name_en)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                tmdb_genre_id = COALESCE(excluded.tmdb_genre_id, genres.tmdb_genre_id),
                name_ru = excluded.name_ru,
                name_en = excluded.name_en
            """,
            (g.get("tmdb_genre_id"), slug, g["name_ru"], g["name_en"]),
        )
        row = conn.execute("SELECT id FROM genres WHERE slug = ?", (slug,)).fetchone()
        genre_map[slug] = int(row["id"])

    platform_map: Dict[str, int] = {}
    for p in dataset.get("platforms", []):
        slug = p["slug"]
        conn.execute(
            """
            INSERT INTO platforms (slug, name, country, platform_type)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                country = excluded.country,
                platform_type = excluded.platform_type
            """,
            (slug, p["name"], p.get("country", "KR"), p.get("platform_type", "TV")),
        )
        row = conn.execute("SELECT id FROM platforms WHERE slug = ?", (slug,)).fetchone()
        platform_map[slug] = int(row["id"])

    trope_map: Dict[str, int] = {}
    for t in dataset.get("tropes", []):
        slug = t["slug"]
        keywords_json = json.dumps(t.get("keywords", []), ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO tropes (slug, name_ru, name_en, category, description, keywords_json, base_weight)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name_ru = excluded.name_ru,
                name_en = excluded.name_en,
                category = excluded.category,
                description = excluded.description,
                keywords_json = excluded.keywords_json,
                base_weight = excluded.base_weight
            """,
            (
                slug,
                t["name_ru"],
                t["name_en"],
                t.get("category", "Сюжет"),
                t.get("description", ""),
                keywords_json,
                float(t.get("base_weight", 0.75)),
            ),
        )
        row = conn.execute("SELECT id FROM tropes WHERE slug = ?", (slug,)).fetchone()
        trope_map[slug] = int(row["id"])

    person_map: Dict[str, int] = {}
    for per in dataset.get("persons", []):
        slug = per["slug"]
        tmdb_pid = per.get("tmdb_person_id")
        existing_p = None
        if tmdb_pid is not None:
            existing_p = conn.execute(
                "SELECT id, slug, name_ru, tmdb_person_id FROM persons WHERE tmdb_person_id = ?",
                (tmdb_pid,),
            ).fetchone()
        if existing_p is None:
            existing_p = conn.execute(
                "SELECT id, slug, name_ru, tmdb_person_id FROM persons WHERE slug = ?",
                (slug,),
            ).fetchone()
            # Если slug занят другой персоной с другим tmdb_person_id — создаём отдельную запись с уникальным slug
            if (
                existing_p is not None
                and tmdb_pid is not None
                and existing_p["tmdb_person_id"] is not None
                and int(existing_p["tmdb_person_id"]) != int(tmdb_pid)
            ):
                slug = f"{slug}-{tmdb_pid}"
                existing_p = conn.execute(
                    "SELECT id, slug, name_ru, tmdb_person_id FROM persons WHERE slug = ?",
                    (slug,),
                ).fetchone()

        if existing_p:
            person_id = int(existing_p["id"])
            incoming_ru = per.get("name_ru", "")
            # Сохраняем кириллическое имя, если из TMDB пришло только латинское
            if _has_cyrillic(existing_p["name_ru"]) and not _has_cyrillic(incoming_ru):
                incoming_ru = existing_p["name_ru"]
            conn.execute(
                """
                UPDATE persons SET
                    tmdb_person_id = COALESCE(tmdb_person_id, ?),
                    name_ru = CASE WHEN ? != '' THEN ? ELSE name_ru END,
                    name_en = CASE WHEN ? != '' THEN ? ELSE name_en END,
                    name_kr = CASE WHEN ? != '' THEN ? ELSE name_kr END,
                    primary_profession = COALESCE(NULLIF(?, ''), primary_profession),
                    birth_year = COALESCE(?, birth_year),
                    bio_short = CASE WHEN ? != '' THEN ? ELSE bio_short END,
                    photo_url = CASE WHEN ? != '' THEN ? ELSE photo_url END
                WHERE id = ?
                """,
                (
                    tmdb_pid,
                    incoming_ru, incoming_ru,
                    per.get("name_en", ""), per.get("name_en", ""),
                    per.get("name_kr", ""), per.get("name_kr", ""),
                    per.get("primary_profession", "Actor"),
                    per.get("birth_year"),
                    per.get("bio_short", ""), per.get("bio_short", ""),
                    per.get("photo_url", ""), per.get("photo_url", ""),
                    person_id,
                ),
            )
            person_map[per["slug"]] = person_id
            person_map[slug] = person_id
            person_map[existing_p["slug"]] = person_id
        else:
            cursor = conn.execute(
                """
                INSERT INTO persons (
                    tmdb_person_id, slug, name_ru, name_en, name_kr,
                    primary_profession, birth_year, bio_short, photo_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tmdb_pid,
                    slug,
                    per["name_ru"],
                    per["name_en"],
                    per.get("name_kr", ""),
                    per.get("primary_profession", "Actor"),
                    per.get("birth_year"),
                    per.get("bio_short", ""),
                    per.get("photo_url", ""),
                ),
            )
            person_id = int(cursor.lastrowid)
            person_map[per["slug"]] = person_id
            person_map[slug] = person_id

    return {
        "genres": genre_map,
        "platforms": platform_map,
        "tropes": trope_map,
        "persons": person_map,
    }


def upsert_drama_bundle(
    conn: sqlite3.Connection,
    drama_data: Dict[str, Any],
    maps: Dict[str, Dict[str, int]],
) -> tuple[int, str]:
    """Выполняет идемпотентный UPSERT дорамы и всех её связей; возвращает (drama_id, 'added'|'updated'|'unchanged')."""
    slug = drama_data["slug"]
    tmdb_id = drama_data.get("tmdb_id")
    new_hash = compute_drama_hash(drama_data)

    existing = None
    if tmdb_id is not None:
        existing = conn.execute(
            "SELECT id, slug, title_ru, synopsis_ru, content_hash FROM dramas WHERE tmdb_id = ?",
            (tmdb_id,),
        ).fetchone()
    if existing is None:
        existing = conn.execute(
            "SELECT id, slug, title_ru, synopsis_ru, content_hash FROM dramas WHERE slug = ?",
            (slug,),
        ).fetchone()

    if existing:
        drama_id = int(existing["id"])
        action = "unchanged" if existing["content_hash"] == new_hash else "updated"
        incoming_title_ru = drama_data["title_ru"]
        if _has_cyrillic(existing["title_ru"]) and not _has_cyrillic(incoming_title_ru):
            incoming_title_ru = existing["title_ru"]
        incoming_synopsis = drama_data.get("synopsis_ru", "")
        if not incoming_synopsis and existing["synopsis_ru"]:
            incoming_synopsis = existing["synopsis_ru"]

        conn.execute(
            """
            UPDATE dramas SET
                tmdb_id = COALESCE(tmdb_id, ?),
                title_ru = ?,
                title_en = ?,
                title_kr = CASE WHEN ? != '' THEN ? ELSE title_kr END,
                title_romaja = CASE WHEN ? != '' THEN ? ELSE title_romaja END,
                synopsis_ru = ?,
                synopsis_en = CASE WHEN ? != '' THEN ? ELSE synopsis_en END,
                release_year = ?,
                first_air_date = CASE WHEN ? != '' THEN ? ELSE first_air_date END,
                episodes_count = ?,
                episode_runtime = ?,
                status = ?,
                rating = ?,
                votes_count = ?,
                popularity_score = ?,
                poster_url = CASE WHEN ? != '' THEN ? ELSE poster_url END,
                backdrop_url = CASE WHEN ? != '' THEN ? ELSE backdrop_url END,
                age_rating = ?,
                content_hash = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                tmdb_id,
                incoming_title_ru,
                drama_data["title_en"],
                drama_data.get("title_kr", ""), drama_data.get("title_kr", ""),
                drama_data.get("title_romaja", ""), drama_data.get("title_romaja", ""),
                incoming_synopsis,
                drama_data.get("synopsis_en", ""), drama_data.get("synopsis_en", ""),
                int(drama_data["release_year"]),
                drama_data.get("first_air_date", ""), drama_data.get("first_air_date", ""),
                int(drama_data.get("episodes_count", 16)),
                int(drama_data.get("episode_runtime", 65)),
                drama_data.get("status", "Completed"),
                float(drama_data.get("rating", 8.0)),
                int(drama_data.get("votes_count", 1000)),
                float(drama_data.get("popularity_score", 50.0)),
                drama_data.get("poster_url", ""), drama_data.get("poster_url", ""),
                drama_data.get("backdrop_url", ""), drama_data.get("backdrop_url", ""),
                drama_data.get("age_rating", "16+"),
                new_hash,
                drama_id,
            ),
        )
    else:
        action = "added"
        cursor = conn.execute(
            """
            INSERT INTO dramas (
                tmdb_id, slug, title_ru, title_en, title_kr, title_romaja,
                synopsis_ru, synopsis_en, release_year, first_air_date,
                episodes_count, episode_runtime, status, rating, votes_count,
                popularity_score, poster_url, backdrop_url, age_rating, content_hash,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                tmdb_id,
                slug,
                drama_data["title_ru"],
                drama_data["title_en"],
                drama_data.get("title_kr", ""),
                drama_data.get("title_romaja", ""),
                drama_data.get("synopsis_ru", ""),
                drama_data.get("synopsis_en", ""),
                int(drama_data["release_year"]),
                drama_data.get("first_air_date", f"{drama_data['release_year']}-01-01"),
                int(drama_data.get("episodes_count", 16)),
                int(drama_data.get("episode_runtime", 65)),
                drama_data.get("status", "Completed"),
                float(drama_data.get("rating", 8.0)),
                int(drama_data.get("votes_count", 1000)),
                float(drama_data.get("popularity_score", 50.0)),
                drama_data.get("poster_url", ""),
                drama_data.get("backdrop_url", ""),
                drama_data.get("age_rating", "16+"),
                new_hash,
            ),
        )
        drama_id = int(cursor.lastrowid)

    # Жанры
    for g_slug in drama_data.get("genres", []):
        genre_id = maps["genres"].get(g_slug)
        if genre_id:
            conn.execute(
                "INSERT INTO drama_genres (drama_id, genre_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                (drama_id, genre_id),
            )

    # Платформы
    for idx, p_slug in enumerate(drama_data.get("platforms", [])):
        platform_id = maps["platforms"].get(p_slug)
        if platform_id:
            conn.execute(
                """
                INSERT INTO drama_platforms (drama_id, platform_id, is_original)
                VALUES (?, ?, ?)
                ON CONFLICT(drama_id, platform_id) DO UPDATE SET is_original = excluded.is_original
                """,
                (drama_id, platform_id, 1 if idx == 0 else 0),
            )

    # Тропы с весами
    for t_entry in drama_data.get("tropes", []):
        if isinstance(t_entry, str):
            t_slug, weight, source = t_entry, 0.80, "manual"
        else:
            t_slug = t_entry["slug"]
            weight = float(t_entry.get("weight", 0.80))
            source = t_entry.get("source", "manual")
        trope_id = maps["tropes"].get(t_slug)
        if trope_id:
            conn.execute(
                """
                INSERT INTO drama_tropes (drama_id, trope_id, weight, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(drama_id, trope_id) DO UPDATE SET
                    weight = MAX(drama_tropes.weight, excluded.weight)
                """,
                (drama_id, trope_id, weight, source),
            )

    # Актёры и режиссёры
    for order_idx, cast_entry in enumerate(drama_data.get("cast", [])):
        p_slug = cast_entry["person"]
        person_id = maps["persons"].get(p_slug)
        if person_id:
            role_type = cast_entry.get("role_type", "Main")
            conn.execute(
                """
                INSERT INTO cast_roles (drama_id, person_id, role_type, character_name, billing_order)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(drama_id, person_id, role_type) DO UPDATE SET
                    character_name = COALESCE(NULLIF(excluded.character_name, ''), cast_roles.character_name),
                    billing_order = MIN(cast_roles.billing_order, excluded.billing_order)
                """,
                (
                    drama_id,
                    person_id,
                    role_type,
                    cast_entry.get("character_name", ""),
                    int(cast_entry.get("billing_order", order_idx + 1)),
                ),
            )

    return drama_id, action


def seed_initial_database(db_manager: Optional[DatabaseManager] = None, force: bool = False) -> Dict[str, int]:
    """Заполняет пустую БД оффлайн-датасетом, системными списками и стартовым логом."""
    manager = db_manager or get_db_manager()
    settings = get_settings()
    dataset_path: Path = settings.offline_dataset_path

    if not dataset_path.exists():
        logger.warning("Offline dataset not found at %s", dataset_path)
        return {"added": 0, "updated": 0}

    with manager.read_session() as conn:
        count_row = conn.execute("SELECT COUNT(*) AS cnt FROM dramas").fetchone()
        existing_count = int(count_row["cnt"]) if count_row else 0

    if existing_count > 0 and not force:
        with manager.write_session() as conn:
            seed_default_lists(conn)
        logger.info("Database already contains %d dramas; skipping initial seed.", existing_count)
        return {"added": 0, "updated": 0}

    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    added_count = 0
    updated_count = 0
    drama_ids_by_slug: Dict[str, int] = {}

    with manager.write_session() as conn:
        seed_default_lists(conn)
        maps = upsert_reference_dictionaries(conn, dataset)

        for drama in dataset.get("dramas", []):
            drama_id, action = upsert_drama_bundle(conn, drama, maps)
            drama_ids_by_slug[drama["slug"]] = drama_id
            if action == "added":
                added_count += 1
            elif action == "updated":
                updated_count += 1

        # Добавляем пару стартовых записей в пользовательские списки для наглядности интерфейса
        demo_assignments = [
            ("favorites", "itaewon-class", 9.5, 16, "Эталонный сюжет про упорство и месть через бизнес."),
            ("favorites", "goblin", 9.7, 16, "Лучший саундтрек и мистическая атмосфера."),
            ("completed", "the-glory", 9.4, 16, "Блестяще продуманная многоходовая месть."),
            ("watching", "queen-of-tears", 9.0, 10, "Сильная химия главных героев и семейная интрига."),
            ("planned", "signal", None, 0, "Рекомендовано по пересечению тропов детектива и времени."),
        ]
        for list_slug, d_slug, rating_val, watched_ep, note in demo_assignments:
            l_row = conn.execute("SELECT id FROM user_lists WHERE slug = ?", (list_slug,)).fetchone()
            d_id = drama_ids_by_slug.get(d_slug)
            if l_row and d_id:
                conn.execute(
                    """
                    INSERT INTO user_list_items (list_id, drama_id, personal_rating, watched_episodes, notes)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(list_id, drama_id) DO NOTHING
                    """,
                    (int(l_row["id"]), d_id, rating_val, watched_ep, note),
                )

        # Записываем факт инициализации в sync_logs
        conn.execute(
            """
            INSERT INTO sync_logs (
                source, trigger_type, status, dramas_scanned,
                dramas_added, dramas_updated, tropes_assigned, details_json, finished_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                "seed",
                "startup",
                "completed",
                len(dataset.get("dramas", [])),
                added_count,
                updated_count,
                sum(len(d.get("tropes", [])) for d in dataset.get("dramas", [])),
                json.dumps(
                    [{"slug": d["slug"], "title_ru": d["title_ru"], "action": "added"} for d in dataset.get("dramas", [])[:8]],
                    ensure_ascii=False,
                ),
            ),
        )

    logger.info("Initial KB seed completed: added=%d, updated=%d", added_count, updated_count)
    return {"added": added_count, "updated": updated_count}
