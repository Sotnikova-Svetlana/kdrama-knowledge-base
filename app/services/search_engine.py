"""Интеллектуальный движок нечёткого поиска (Fuzzy Search), коррекции раскладки и автоподсказок.

Поддерживает:
- Двунаправленную коррекцию раскладки клавиатуры QWERTY (EN) <-> ЙЦУКЕН (RU);
- Исправление опечаток на основе гибридного скоринга RapidFuzz (WRatio + Damerau-Levenshtein);
- Индексацию дорам (RU/EN/KR/Romaja), актёров и сюжетных тропов в памяти;
- Мгновенные сгруппированные автоподсказки (autocomplete) и запись телеметрии.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz
from rapidfuzz.distance import DamerauLevenshtein

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.db.repositories.dramas_repo import DramasRepository
from app.db.repositories.sync_repo import SyncTelemetryRepository

logger = get_logger(__name__)


EN_LAYOUT = "`qwertyuiop[]asdfghjkl;'zxcvbnm,.~QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?"
RU_LAYOUT = "ёйцукенгшщзхъфывапролджэячсмитьбюЁЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,"

EN_TO_RU_MAP = str.maketrans(EN_LAYOUT, RU_LAYOUT)
RU_TO_EN_MAP = str.maketrans(RU_LAYOUT, EN_LAYOUT)

CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")
LATIN_RE = re.compile(r"[a-zA-Z]")
HANGUL_RE = re.compile(r"[\uac00-\ud7af]")


def normalize_text(text: str) -> str:
    """Приводит строку к единому виду для сопоставления: нижний регистр, ё->е, сжатие пробелов."""
    cleaned = text.strip().lower().replace("ё", "е")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def convert_en_to_ru(text: str) -> str:
    """Преобразует строку, набранную в английской раскладке, в русскую ЙЦУКЕН."""
    return text.translate(EN_TO_RU_MAP)


def convert_ru_to_en(text: str) -> str:
    """Преобразует строку, набранную в русской раскладке, в английскую QWERTY."""
    return text.translate(RU_TO_EN_MAP)


def has_cyrillic(text: str) -> bool:
    return bool(CYRILLIC_RE.search(text))


def has_latin(text: str) -> bool:
    return bool(LATIN_RE.search(text))


def has_hangul(text: str) -> bool:
    return bool(HANGUL_RE.search(text))


def looks_like_wrong_en_layout(text: str) -> bool:
    """Эвристика: содержит ли латинская строка характерные знаки русской раскладки ([, ], ;, ', `, ,)."""
    if has_cyrillic(text) or has_hangul(text):
        return False
    special_ru_keys = set("[];'`,.")
    if any(ch in special_ru_keys for ch in text):
        return True
    # Сочетания согласных, нетипичные для английского, но частые при наборе русских слов латиницей
    unusual_clusters = ("ghb", "rjh", "dby", "uj,", "ck`", "ckf", "bn[", "cbv", "ntk", "crj")
    low = text.lower()
    return any(cluster in low for cluster in unusual_clusters)


@dataclass
class IndexedField:
    text: str
    norm_text: str
    field_name: str
    boost: float


@dataclass
class DramaSearchEntry:
    drama_id: int
    slug: str
    title_ru: str
    title_en: str
    fields: List[IndexedField]


@dataclass
class EntitySuggestionEntry:
    entity_type: str  # "person" | "trope"
    entity_id: int
    slug: str
    label: str
    sublabel: str
    search_variants: List[str]


class FuzzySearchEngine:
    """Поисковый движок БЗ в памяти с переиндексацией после обновлений."""

    def __init__(
        self,
        dramas_repo: Optional[DramasRepository] = None,
        telemetry_repo: Optional[SyncTelemetryRepository] = None,
    ) -> None:
        self.settings = get_settings()
        self.dramas_repo = dramas_repo or DramasRepository()
        self.telemetry_repo = telemetry_repo or SyncTelemetryRepository()
        self._drama_entries: List[DramaSearchEntry] = []
        self._entity_entries: List[EntitySuggestionEntry] = []
        self._drama_cache_by_id: Dict[int, Dict[str, Any]] = {}
        self.rebuild_index()

    def rebuild_index(self) -> int:
        """Перестраивает поисковый индекс из реляционной БЗ."""
        vectors = self.dramas_repo.get_all_feature_vectors()
        drama_entries: List[DramaSearchEntry] = []
        cache_by_id: Dict[int, Dict[str, Any]] = {}
        seen_persons: Dict[int, EntitySuggestionEntry] = {}
        seen_tropes: Dict[int, EntitySuggestionEntry] = {}

        for d in vectors:
            did = int(d["id"])
            cache_by_id[did] = d
            fields: List[IndexedField] = []

            def add_field(val: str, name: str, boost: float) -> None:
                if val and val.strip():
                    fields.append(
                        IndexedField(
                            text=val.strip(),
                            norm_text=normalize_text(val),
                            field_name=name,
                            boost=boost,
                        )
                    )

            add_field(d["title_ru"], "title_ru", 1.00)
            add_field(d["title_en"], "title_en", 0.96)
            add_field(d.get("title_kr", ""), "title_kr", 0.95)
            add_field(d.get("title_romaja", ""), "title_romaja", 0.92)

            for person in d.get("cast", []):
                p_name_ru = person.get("name_ru", "")
                p_name_en = person.get("name_en", "")
                add_field(p_name_ru, "person", 0.86)
                add_field(p_name_en, "person", 0.84)
                pid = int(person["person_id"])
                if pid not in seen_persons:
                    seen_persons[pid] = EntitySuggestionEntry(
                        entity_type="person",
                        entity_id=pid,
                        slug=person["slug"],
                        label=p_name_ru,
                        sublabel=f"{p_name_en} · {person.get('role_type', 'Actor')}",
                        search_variants=[
                            normalize_text(v)
                            for v in (p_name_ru, p_name_en)
                            if v
                        ],
                    )

            for trope in d.get("tropes", []):
                t_name = trope.get("name_ru", "")
                add_field(t_name, "trope", 0.80)
                tid = int(trope["trope_id"])
                if tid not in seen_tropes:
                    seen_tropes[tid] = EntitySuggestionEntry(
                        entity_type="trope",
                        entity_id=tid,
                        slug=trope["slug"],
                        label=t_name,
                        sublabel=f"Троп · {trope.get('category', 'Сюжет')}",
                        search_variants=[normalize_text(t_name)],
                    )

            drama_entries.append(
                DramaSearchEntry(
                    drama_id=did,
                    slug=d["slug"],
                    title_ru=d["title_ru"],
                    title_en=d["title_en"],
                    fields=fields,
                )
            )

        self._drama_entries = drama_entries
        self._entity_entries = [*seen_persons.values(), *seen_tropes.values()]
        self._drama_cache_by_id = cache_by_id
        logger.info(
            "Fuzzy search index rebuilt: %d dramas, %d entities",
            len(self._drama_entries),
            len(self._entity_entries),
        )
        return len(self._drama_entries)

    def _score_query_against_entries(self, norm_query: str) -> List[Tuple[DramaSearchEntry, float, str, str]]:
        """Оценивает релевантность нормализованного запроса ко всем дорамам."""
        if not norm_query:
            return []

        scored: List[Tuple[DramaSearchEntry, float, str, str]] = []
        q_len = len(norm_query)

        for entry in self._drama_entries:
            best_score = 0.0
            best_field = "title_ru"
            best_text = entry.title_ru

            for field in entry.fields:
                target = field.norm_text
                if not target:
                    continue

                if norm_query == target:
                    raw_score = 100.0
                elif target.startswith(norm_query) and q_len >= 2:
                    raw_score = 96.0 + min(3.0, q_len * 0.2)
                elif norm_query in target and q_len >= 3:
                    raw_score = 90.0 + min(5.0, (q_len / max(len(target), 1)) * 5.0)
                else:
                    w_ratio = fuzz.WRatio(norm_query, target)
                    d_sim = DamerauLevenshtein.normalized_similarity(norm_query, target) * 100.0
                    p_ratio = fuzz.partial_ratio(norm_query, target) if q_len >= 4 else 0.0
                    # Комбинированная метрика предотвращает ложные короткие совпадения
                    raw_score = max(w_ratio * 0.65 + d_sim * 0.35, p_ratio * 0.88 if len(target) > q_len + 3 else 0.0)

                weighted = raw_score * field.boost
                if weighted > best_score:
                    best_score = weighted
                    best_field = field.field_name
                    best_text = field.text

            if best_score >= self.settings.fuzzy_min_score:
                scored.append((entry, round(best_score, 2), best_field, best_text))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored

    def search(
        self,
        raw_query: str,
        limit: int = 24,
        record_telemetry: bool = True,
        disable_layout_fix: bool = False,
    ) -> Dict[str, Any]:
        """Выполняет интеллектуальный поиск с автоисправлением раскладки и опечаток."""
        started = time.perf_counter()
        cleaned_raw = raw_query.strip()
        if not cleaned_raw:
            return {
                "raw_query": raw_query,
                "effective_query": "",
                "corrected_query": None,
                "correction_kind": "none",
                "was_corrected": False,
                "banner_message": None,
                "latency_ms": 0.0,
                "total": 0,
                "results": [],
            }

        norm_original = normalize_text(cleaned_raw)
        orig_hits = self._score_query_against_entries(norm_original)
        orig_top_score = orig_hits[0][1] if orig_hits else 0.0

        chosen_hits = orig_hits
        effective_query = cleaned_raw
        corrected_query: Optional[str] = None
        correction_kind = "none"

        # 1. Проверяем альтернативную раскладку клавиатуры (EN <-> RU)
        if not disable_layout_fix and not has_hangul(cleaned_raw):
            alt_text: Optional[str] = None
            if has_latin(cleaned_raw) and not has_cyrillic(cleaned_raw):
                alt_text = convert_en_to_ru(cleaned_raw)
            elif has_cyrillic(cleaned_raw) and not has_latin(cleaned_raw):
                alt_text = convert_ru_to_en(cleaned_raw)

            if alt_text:
                norm_alt = normalize_text(alt_text)
                alt_hits = self._score_query_against_entries(norm_alt)
                alt_top_score = alt_hits[0][1] if alt_hits else 0.0

                should_switch_layout = (
                    alt_top_score > orig_top_score + 6.0
                    or (looks_like_wrong_en_layout(cleaned_raw) and alt_top_score >= self.settings.fuzzy_min_score)
                )
                if should_switch_layout and alt_hits:
                    chosen_hits = alt_hits
                    effective_query = alt_text
                    top_entry, top_score, top_field, top_matched = alt_hits[0]
                    if top_score < 95.0 and top_field in ("title_ru", "title_en"):
                        correction_kind = "layout_and_typo"
                        corrected_query = top_matched
                    else:
                        correction_kind = "layout"
                        corrected_query = top_matched if top_field in ("title_ru", "title_en") else alt_text

        # 2. Если раскладка не менялась, проверяем опечатку / точное совпадение
        if correction_kind == "none" and chosen_hits:
            top_entry, top_score, top_field, top_matched = chosen_hits[0]
            norm_matched = normalize_text(top_matched)
            if norm_original == norm_matched or norm_matched.startswith(norm_original):
                correction_kind = "exact"
            elif top_score < 95.5 and top_field in ("title_ru", "title_en", "title_romaja"):
                correction_kind = "typo"
                corrected_query = top_matched
                effective_query = top_matched

        was_corrected = correction_kind in ("typo", "layout", "layout_and_typo") and corrected_query is not None
        banner_message: Optional[str] = None
        if was_corrected and corrected_query:
            if correction_kind == "layout":
                banner_message = f"Показаны результаты для «{corrected_query}» (исправлена раскладка клавиатуры)"
            elif correction_kind == "layout_and_typo":
                banner_message = f"Показаны результаты для «{corrected_query}» (исправлена раскладка и опечатка)"
            else:
                banner_message = f"Показаны результаты для «{corrected_query}» (исправлена опечатка)"

        # Гидрируем полные сводки дорам
        top_hits = chosen_hits[:limit]
        drama_ids = [item[0].drama_id for item in top_hits]
        summaries = self.dramas_repo.get_dramas_by_ids(drama_ids)

        results: List[Dict[str, Any]] = []
        for entry, score, field_name, matched_text in top_hits:
            summary = summaries.get(entry.drama_id)
            if summary:
                results.append(
                    {
                        "drama": summary,
                        "score": score,
                        "match_field": field_name,
                        "matched_text": matched_text,
                    }
                )

        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)

        if record_telemetry:
            self.telemetry_repo.record_search_telemetry(
                raw_query=cleaned_raw,
                normalized_query=norm_original,
                corrected_query=corrected_query or effective_query,
                correction_type=correction_kind,
                top_score=chosen_hits[0][1] if chosen_hits else 0.0,
                results_count=len(results),
                latency_ms=latency_ms,
            )

        return {
            "raw_query": cleaned_raw,
            "effective_query": effective_query,
            "corrected_query": corrected_query,
            "correction_kind": correction_kind,
            "was_corrected": was_corrected,
            "banner_message": banner_message,
            "latency_ms": latency_ms,
            "total": len(chosen_hits),
            "results": results,
        }

    def autocomplete(self, raw_query: str, limit: Optional[int] = None) -> Dict[str, Any]:
        """Возвращает быстрые сгруппированные автоподсказки (дорамы, персоны, тропы)."""
        started = time.perf_counter()
        cleaned = raw_query.strip()
        max_items = limit or self.settings.autocomplete_limit

        if len(cleaned) < 1:
            return {
                "raw_query": raw_query,
                "converted_query": None,
                "correction_hint": None,
                "latency_ms": 0.0,
                "items": [],
            }

        norm_q = normalize_text(cleaned)
        alt_q: Optional[str] = None
        if has_latin(cleaned) and not has_cyrillic(cleaned):
            alt_q = normalize_text(convert_en_to_ru(cleaned))
        elif has_cyrillic(cleaned) and not has_latin(cleaned):
            alt_q = normalize_text(convert_ru_to_en(cleaned))

        # Подбираем лучший вариант между исходным и переключённой раскладкой
        drama_candidates_orig = self._score_query_against_entries(norm_q)
        drama_candidates_alt = self._score_query_against_entries(alt_q) if alt_q else []

        use_alt = bool(
            drama_candidates_alt
            and (
                not drama_candidates_orig
                or drama_candidates_alt[0][1] > drama_candidates_orig[0][1] + 6.0
                or looks_like_wrong_en_layout(cleaned)
            )
        )
        active_q = alt_q if (use_alt and alt_q) else norm_q
        active_dramas = drama_candidates_alt if use_alt else drama_candidates_orig

        suggestions: List[Dict[str, Any]] = []

        # Топ-5 дорам
        for entry, score, _field, _matched in active_dramas[:5]:
            drama_obj = self._drama_cache_by_id.get(entry.drama_id, {})
            suggestions.append(
                {
                    "entity_type": "drama",
                    "id": entry.drama_id,
                    "slug": entry.slug,
                    "label": entry.title_ru,
                    "sublabel": f"{entry.title_en} · {drama_obj.get('release_year', '')} · ★ {drama_obj.get('rating', '')}",
                    "score": score,
                }
            )

        # Топ-3 персоны и топ-2 тропа
        entity_hits: List[Tuple[EntitySuggestionEntry, float]] = []
        for ent in self._entity_entries:
            best = 0.0
            for variant in ent.search_variants:
                if active_q in variant:
                    best = max(best, 94.0 if variant.startswith(active_q) else 88.0)
                else:
                    best = max(best, fuzz.WRatio(active_q, variant))
            if best >= 68.0:
                entity_hits.append((ent, round(best, 2)))

        entity_hits.sort(key=lambda x: x[1], reverse=True)
        for ent, score in entity_hits[:5]:
            suggestions.append(
                {
                    "entity_type": ent.entity_type,
                    "id": ent.entity_id,
                    "slug": ent.slug,
                    "label": ent.label,
                    "sublabel": ent.sublabel,
                    "score": score,
                }
            )

        suggestions.sort(key=lambda x: (0 if x["entity_type"] == "drama" else 1, -x["score"]))
        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)

        return {
            "raw_query": cleaned,
            "converted_query": active_q if use_alt else None,
            "correction_hint": f"Раскладка: «{active_q}»" if use_alt else None,
            "latency_ms": latency_ms,
            "items": suggestions[:max_items],
        }


_search_engine: Optional[FuzzySearchEngine] = None


def get_search_engine() -> FuzzySearchEngine:
    """Возвращает синглтон поискового движка."""
    global _search_engine
    if _search_engine is None:
        _search_engine = FuzzySearchEngine()
    return _search_engine
