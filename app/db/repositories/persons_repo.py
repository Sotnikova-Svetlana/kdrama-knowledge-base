"""Репозиторий для работы с персонами (актёрами, режиссёрами, сценаристами) и их фильмографией."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.exceptions import EntityNotFoundError
from app.db.connection import DatabaseManager, get_db_manager


class PersonsRepository:
    """Доступ к таблице persons и связанным ролям в cast_roles."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or get_db_manager()

    def list_persons(
        self,
        profession: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Возвращает список персон с количеством проектов в базе знаний."""
        clauses = ["1=1"]
        params: List[Any] = []

        if profession:
            clauses.append("p.primary_profession = ?")
            params.append(profession)

        if query:
            like = f"%{query.strip()}%"
            clauses.append("(p.name_ru LIKE ? OR p.name_en LIKE ? OR p.name_kr LIKE ?)")
            params.extend([like, like, like])

        where_sql = " AND ".join(clauses)
        with self.db.read_session() as conn:
            rows = conn.execute(
                f"""
                SELECT p.*, COUNT(DISTINCT cr.drama_id) AS dramas_count
                FROM persons p
                LEFT JOIN cast_roles cr ON cr.person_id = p.id
                WHERE {where_sql}
                GROUP BY p.id
                ORDER BY dramas_count DESC, p.name_ru ASC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
            return [dict(r) for r in rows]

    def get_person_detail(self, person_id: int) -> Dict[str, Any]:
        """Возвращает профиль персоны и её фильмографию в БЗ."""
        with self.db.read_session() as conn:
            person_row = conn.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()
            if not person_row:
                raise EntityNotFoundError("Персона", person_id)

            person = dict(person_row)
            filmography_rows = conn.execute(
                """
                SELECT d.id, d.slug, d.title_ru, d.title_en, d.title_kr,
                       d.release_year, d.rating, d.status, d.poster_url,
                       cr.role_type, cr.character_name
                FROM cast_roles cr
                JOIN dramas d ON d.id = cr.drama_id
                WHERE cr.person_id = ?
                ORDER BY d.release_year DESC, d.rating DESC
                """,
                (person_id,),
            ).fetchall()

            person["filmography"] = [dict(r) for r in filmography_rows]
            return person
