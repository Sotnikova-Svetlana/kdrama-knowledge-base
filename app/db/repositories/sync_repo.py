"""Репозиторий для журнала синхронизаций, телеметрии поиска и статистики схемы БЗ."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.db.connection import DatabaseManager, get_db_manager
from app.db.schema import inspect_schema_stats


class SyncTelemetryRepository:
    """Управляет таблицами sync_logs, search_telemetry и сводной аналитикой БЗ."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or get_db_manager()

    def create_sync_log(self, source: str, trigger_type: str) -> int:
        """Создаёт запись о начале синхронизации и возвращает её ID."""
        with self.db.write_session() as conn:
            cursor = conn.execute(
                """
                INSERT INTO sync_logs (source, trigger_type, status)
                VALUES (?, ?, 'running')
                """,
                (source, trigger_type),
            )
            return int(cursor.lastrowid)

    def complete_sync_log(
        self,
        log_id: int,
        status: str,
        dramas_scanned: int,
        dramas_added: int,
        dramas_updated: int,
        tropes_assigned: int,
        details: List[Dict[str, Any]],
        error_message: str = "",
    ) -> None:
        """Фиксирует итоги выполнения задачи синхронизации."""
        with self.db.write_session() as conn:
            conn.execute(
                """
                UPDATE sync_logs
                SET status = ?,
                    dramas_scanned = ?,
                    dramas_added = ?,
                    dramas_updated = ?,
                    tropes_assigned = ?,
                    details_json = ?,
                    error_message = ?,
                    finished_at = datetime('now')
                WHERE id = ?
                """,
                (
                    status,
                    dramas_scanned,
                    dramas_added,
                    dramas_updated,
                    tropes_assigned,
                    json.dumps(details, ensure_ascii=False),
                    error_message,
                    log_id,
                ),
            )

    def get_sync_logs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Возвращает историю последних синхронизаций с распарсенными деталями."""
        with self.db.read_session() as conn:
            rows = conn.execute(
                """
                SELECT * FROM sync_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            logs: List[Dict[str, Any]] = []
            for r in rows:
                item = dict(r)
                try:
                    item["details"] = json.loads(item.get("details_json") or "[]")
                except json.JSONDecodeError:
                    item["details"] = []
                logs.append(item)
            return logs

    def record_search_telemetry(
        self,
        raw_query: str,
        normalized_query: str,
        corrected_query: str,
        correction_type: str,
        top_score: float,
        results_count: int,
        latency_ms: float,
    ) -> None:
        """Сохраняет метрику выполненного поискового запроса."""
        with self.db.write_session() as conn:
            conn.execute(
                """
                INSERT INTO search_telemetry (
                    raw_query, normalized_query, corrected_query,
                    correction_type, top_score, results_count, latency_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    raw_query,
                    normalized_query,
                    corrected_query,
                    correction_type,
                    round(float(top_score), 2),
                    int(results_count),
                    round(float(latency_ms), 3),
                ),
            )

    def get_kb_overview(self) -> Dict[str, Any]:
        """Возвращает сводную статистику по БЗ и всем 13 SQL-таблицам."""
        with self.db.read_session() as conn:
            schema_tables = inspect_schema_stats(conn)
            counts_row = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM dramas) AS dramas_count,
                    (SELECT COUNT(*) FROM dramas WHERE status = 'Ongoing') AS ongoing_count,
                    (SELECT COUNT(*) FROM persons) AS persons_count,
                    (SELECT COUNT(*) FROM tropes) AS tropes_count,
                    (SELECT COUNT(*) FROM genres) AS genres_count,
                    (SELECT COUNT(*) FROM platforms) AS platforms_count,
                    (SELECT COUNT(*) FROM drama_tropes) AS trope_links_count,
                    (SELECT COUNT(*) FROM cast_roles) AS cast_links_count,
                    (SELECT ROUND(AVG(rating), 2) FROM dramas) AS avg_rating,
                    (SELECT MAX(finished_at) FROM sync_logs WHERE status IN ('completed', 'partial')) AS last_sync_at
                """
            ).fetchone()
            recent_telemetry = conn.execute(
                """
                SELECT raw_query, corrected_query, correction_type, top_score, results_count, latency_ms, created_at
                FROM search_telemetry
                ORDER BY id DESC
                LIMIT 15
                """
            ).fetchall()

        overview = dict(counts_row) if counts_row else {}
        overview["tables"] = schema_tables
        overview["tables_count"] = len(schema_tables)
        overview["recent_searches"] = [dict(r) for r in recent_telemetry]
        return overview
