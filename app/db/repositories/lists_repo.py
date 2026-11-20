"""Репозиторий для пользовательских списков и личных оценок дорам."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.exceptions import EntityNotFoundError, ValidationConflictError
from app.db.connection import DatabaseManager, get_db_manager
from app.db.seed import slugify_text


class ListsRepository:
    """Управляет таблицами user_lists и user_list_items."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or get_db_manager()

    def get_all_lists(self) -> List[Dict[str, Any]]:
        """Возвращает все списки вместе с входящими в них дорамами."""
        with self.db.read_session() as conn:
            lists_rows = conn.execute(
                """
                SELECT ul.*, COUNT(uli.id) AS items_count
                FROM user_lists ul
                LEFT JOIN user_list_items uli ON uli.list_id = ul.id
                GROUP BY ul.id
                ORDER BY ul.is_system DESC, ul.id ASC
                """
            ).fetchall()

            result: List[Dict[str, Any]] = []
            for l_row in lists_rows:
                lst = dict(l_row)
                items_rows = conn.execute(
                    """
                    SELECT uli.id AS item_id, uli.personal_rating, uli.watched_episodes,
                           uli.notes, uli.added_at, uli.updated_at,
                           d.id AS drama_id, d.slug AS drama_slug, d.title_ru, d.title_en,
                           d.title_kr, d.release_year, d.episodes_count, d.status,
                           d.rating AS global_rating, d.poster_url
                    FROM user_list_items uli
                    JOIN dramas d ON d.id = uli.drama_id
                    WHERE uli.list_id = ?
                    ORDER BY uli.updated_at DESC
                    """,
                    (lst["id"],),
                ).fetchall()
                lst["items"] = [dict(ir) for ir in items_rows]
                result.append(lst)
            return result

    def create_custom_list(self, name: str, description: str = "") -> Dict[str, Any]:
        """Создаёт новый пользовательский список."""
        clean_name = name.strip()
        if not clean_name:
            raise ValidationConflictError("Название списка не может быть пустым.")
        slug = slugify_text(clean_name)

        with self.db.write_session() as conn:
            existing = conn.execute(
                "SELECT id FROM user_lists WHERE slug = ? OR name = ?",
                (slug, clean_name),
            ).fetchone()
            if existing:
                raise ValidationConflictError(f"Список «{clean_name}» уже существует.")

            cursor = conn.execute(
                """
                INSERT INTO user_lists (slug, name, list_type, description, is_system)
                VALUES (?, ?, 'custom', ?, 0)
                """,
                (slug, clean_name, description.strip()),
            )
            new_id = cursor.lastrowid
            row = conn.execute("SELECT * FROM user_lists WHERE id = ?", (new_id,)).fetchone()
            created = dict(row)
            created["items_count"] = 0
            created["items"] = []
            return created

    def delete_custom_list(self, list_id: int) -> None:
        """Удаляет кастомный список (системные списки защищены)."""
        with self.db.write_session() as conn:
            row = conn.execute("SELECT is_system FROM user_lists WHERE id = ?", (list_id,)).fetchone()
            if not row:
                raise EntityNotFoundError("Список", list_id)
            if int(row["is_system"]) == 1:
                raise ValidationConflictError("Системные списки просмотра нельзя удалить.")
            conn.execute("DELETE FROM user_lists WHERE id = ?", (list_id,))

    def upsert_list_item(
        self,
        list_id: int,
        drama_id: int,
        personal_rating: Optional[float] = None,
        watched_episodes: int = 0,
        notes: str = "",
    ) -> Dict[str, Any]:
        """Добавляет дораму в список или обновляет её статус/оценку/заметку."""
        with self.db.write_session() as conn:
            l_row = conn.execute("SELECT id FROM user_lists WHERE id = ?", (list_id,)).fetchone()
            if not l_row:
                raise EntityNotFoundError("Список", list_id)

            d_row = conn.execute(
                "SELECT id, episodes_count FROM dramas WHERE id = ?",
                (drama_id,),
            ).fetchone()
            if not d_row:
                raise EntityNotFoundError("Дорама", drama_id)

            safe_watched = max(0, min(int(watched_episodes), int(d_row["episodes_count"])))
            conn.execute(
                """
                INSERT INTO user_list_items (list_id, drama_id, personal_rating, watched_episodes, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(list_id, drama_id) DO UPDATE SET
                    personal_rating = excluded.personal_rating,
                    watched_episodes = excluded.watched_episodes,
                    notes = excluded.notes,
                    updated_at = datetime('now')
                """,
                (list_id, drama_id, personal_rating, safe_watched, notes.strip()),
            )
            item_row = conn.execute(
                """
                SELECT uli.*, d.title_ru, d.slug AS drama_slug
                FROM user_list_items uli
                JOIN dramas d ON d.id = uli.drama_id
                WHERE uli.list_id = ? AND uli.drama_id = ?
                """,
                (list_id, drama_id),
            ).fetchone()
            return dict(item_row)

    def remove_list_item(self, list_id: int, drama_id: int) -> None:
        """Удаляет дораму из указанного списка."""
        with self.db.write_session() as conn:
            cursor = conn.execute(
                "DELETE FROM user_list_items WHERE list_id = ? AND drama_id = ?",
                (list_id, drama_id),
            )
            if cursor.rowcount == 0:
                raise EntityNotFoundError("Запись в списке", f"{list_id}:{drama_id}")
