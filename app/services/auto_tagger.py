"""Автоматический извлекатель сюжетных тропов на основе продукционных правил и ключевых слов.

Анализирует русский/английский синопсис, название и теги внешнего источника (TMDB),
сопоставляя лексические паттерны со словарём тропов из таблицы `tropes`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.db.connection import DatabaseManager, get_db_manager


@dataclass
class ExtractedTrope:
    trope_id: int
    slug: str
    name_ru: str
    weight: float
    matched_keywords: List[str]


class TropeAutoTagger:
    """Продукционный анализатор текста для автоматической разметки дорам тропами БЗ."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or get_db_manager()
        self._rules_cache: Optional[List[Dict[str, object]]] = None

    def load_rules(self, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, object]]:
        """Загружает правила ключевых слов из таблицы tropes."""
        if conn is not None:
            rows = conn.execute(
                "SELECT id, slug, name_ru, keywords_json, base_weight FROM tropes"
            ).fetchall()
        else:
            with self.db.read_session() as read_conn:
                rows = read_conn.execute(
                    "SELECT id, slug, name_ru, keywords_json, base_weight FROM tropes"
                ).fetchall()

        rules: List[Dict[str, object]] = []
        for r in rows:
            try:
                keywords = json.loads(r["keywords_json"] or "[]")
            except json.JSONDecodeError:
                keywords = []
            rules.append(
                {
                    "id": int(r["id"]),
                    "slug": str(r["slug"]),
                    "name_ru": str(r["name_ru"]),
                    "keywords": [str(k).lower().strip() for k in keywords if str(k).strip()],
                    "base_weight": float(r["base_weight"]),
                }
            )
        self._rules_cache = rules
        return rules

    def extract_tropes(
        self,
        synopsis_ru: str,
        synopsis_en: str = "",
        extra_keywords: Optional[List[str]] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> List[ExtractedTrope]:
        """Извлекает сюжетные тропы и вычисляет их вес по числу совпавших триггеров."""
        rules = self.load_rules(conn) if conn is not None or self._rules_cache is None else self._rules_cache
        corpus_parts = [synopsis_ru or "", synopsis_en or ""]
        if extra_keywords:
            corpus_parts.extend(extra_keywords)
        corpus = " ".join(corpus_parts).lower().replace("ё", "е")

        if not corpus.strip():
            return []

        results: List[ExtractedTrope] = []
        for rule in rules:
            matched: List[str] = []
            for kw in rule["keywords"]:
                norm_kw = kw.replace("ё", "е")
                if norm_kw in corpus:
                    matched.append(kw)

            if matched:
                base_w = float(rule["base_weight"])
                # Усиливаем вес при нескольких независимых совпадениях, ограничивая сверху 0.98
                bonus = min(0.14, (len(matched) - 1) * 0.05)
                final_weight = round(min(0.98, max(0.55, base_w * 0.92 + bonus)), 2)
                results.append(
                    ExtractedTrope(
                        trope_id=int(rule["id"]),
                        slug=str(rule["slug"]),
                        name_ru=str(rule["name_ru"]),
                        weight=final_weight,
                        matched_keywords=matched,
                    )
                )

        results.sort(key=lambda item: item.weight, reverse=True)
        return results

    def apply_auto_tags(
        self,
        conn: sqlite3.Connection,
        drama_id: int,
        synopsis_ru: str,
        synopsis_en: str = "",
        extra_keywords: Optional[List[str]] = None,
    ) -> List[ExtractedTrope]:
        """Извлекает и сохраняет тропы в таблицу drama_tropes без перезаписи ручных более высоких весов."""
        extracted = self.extract_tropes(
            synopsis_ru=synopsis_ru,
            synopsis_en=synopsis_en,
            extra_keywords=extra_keywords,
            conn=conn,
        )
        for item in extracted:
            conn.execute(
                """
                INSERT INTO drama_tropes (drama_id, trope_id, weight, source, matched_keywords)
                VALUES (?, ?, ?, 'auto_tagger', ?)
                ON CONFLICT(drama_id, trope_id) DO UPDATE SET
                    weight = MAX(drama_tropes.weight, excluded.weight),
                    matched_keywords = CASE
                        WHEN drama_tropes.matched_keywords = '' THEN excluded.matched_keywords
                        ELSE drama_tropes.matched_keywords
                    END
                """,
                (
                    drama_id,
                    item.trope_id,
                    item.weight,
                    ", ".join(item.matched_keywords),
                ),
            )
        return extracted
