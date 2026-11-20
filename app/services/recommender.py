"""Контентно-семантический механизм рекомендаций дорам с объяснимостью (XAI).

Вычисляет семантическую близость между целевой дорамой и кандидатами на основе:
1. Косинусного сходства взвешенных векторов сюжетных тропов (0.50);
2. Индекса Жаккара по множеству жанров (0.25);
3. Взвешенного пересечения актёрского состава и режиссёров/сценаристов (0.20);
4. Близости эпохи выпуска и зрительского рейтинга (0.05).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import get_settings
from app.core.exceptions import EntityNotFoundError
from app.db.repositories.dramas_repo import DramasRepository


ROLE_WEIGHTS: Dict[str, float] = {
    "Main": 1.0,
    "Director": 0.9,
    "Writer": 0.9,
    "Support": 0.55,
    "Cameo": 0.25,
}


def cosine_similarity_dicts(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    """Вычисляет косинусное сходство двух разреженных взвешенных векторов."""
    if not vec_a or not vec_b:
        return 0.0
    common = set(vec_a.keys()) & set(vec_b.keys())
    if not common:
        return 0.0
    dot = sum(vec_a[k] * vec_b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Вычисляет коэффициент Жаккара для двух множеств."""
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def weighted_cast_similarity(
    cast_a: Dict[str, Tuple[float, str]],
    cast_b: Dict[str, Tuple[float, str]],
) -> Tuple[float, List[str]]:
    """Вычисляет взвешенное пересечение актёров/создателей и список общих имён."""
    if not cast_a or not cast_b:
        return 0.0, []
    common_slugs = set(cast_a.keys()) & set(cast_b.keys())
    if not common_slugs:
        return 0.0, []

    num = sum(min(cast_a[s][0], cast_b[s][0]) for s in common_slugs)
    den = sum(max(cast_a.get(s, (0.0, ""))[0], cast_b.get(s, (0.0, ""))[0]) for s in (set(cast_a) | set(cast_b)))
    shared_names = [cast_a[s][1] for s in sorted(common_slugs)]
    return (num / den if den > 0 else 0.0), shared_names


class RecommenderService:
    """Сервис расчёта похожих дорам и объяснения причин рекомендации."""

    def __init__(self, dramas_repo: Optional[DramasRepository] = None) -> None:
        self.settings = get_settings()
        self.dramas_repo = dramas_repo or DramasRepository()

    def get_similar_dramas(self, drama_id: int, limit: int = 6) -> Dict[str, Any]:
        """Подбирает топ-N похожих дорам с детализацией факторов сходства."""
        all_vectors = self.dramas_repo.get_all_feature_vectors()
        by_id = {int(d["id"]): d for d in all_vectors}

        source = by_id.get(drama_id)
        if not source:
            raise EntityNotFoundError("Дорама", drama_id)

        return self._compute_recommendations(source, all_vectors, limit=limit)

    def get_similar_by_slug(self, slug: str, limit: int = 6) -> Dict[str, Any]:
        """Подбирает похожие дорамы по slug исходной дорамы."""
        all_vectors = self.dramas_repo.get_all_feature_vectors()
        source = next((d for d in all_vectors if d["slug"] == slug), None)
        if not source:
            raise EntityNotFoundError("Дорама", slug)
        return self._compute_recommendations(source, all_vectors, limit=limit)

    def _compute_recommendations(
        self,
        source: Dict[str, Any],
        all_vectors: List[Dict[str, Any]],
        limit: int,
    ) -> Dict[str, Any]:
        src_id = int(source["id"])
        src_tropes = {t["slug"]: float(t["weight"]) for t in source.get("tropes", [])}
        src_trope_names = {t["slug"]: t["name_ru"] for t in source.get("tropes", [])}
        src_genres = {g["slug"] for g in source.get("genres", [])}
        src_genre_names = {g["slug"]: g["name_ru"] for g in source.get("genres", [])}
        src_cast = {
            c["slug"]: (ROLE_WEIGHTS.get(c.get("role_type", "Support"), 0.5), c["name_ru"])
            for c in source.get("cast", [])
        }

        scored: List[Tuple[Dict[str, Any], float, Dict[str, Any]]] = []

        for cand in all_vectors:
            if int(cand["id"]) == src_id:
                continue

            cand_tropes = {t["slug"]: float(t["weight"]) for t in cand.get("tropes", [])}
            cand_genres = {g["slug"] for g in cand.get("genres", [])}
            cand_cast = {
                c["slug"]: (ROLE_WEIGHTS.get(c.get("role_type", "Support"), 0.5), c["name_ru"])
                for c in cand.get("cast", [])
            }

            trope_sim = cosine_similarity_dicts(src_tropes, cand_tropes)
            genre_sim = jaccard_similarity(src_genres, cand_genres)
            cast_sim, shared_persons = weighted_cast_similarity(src_cast, cand_cast)

            year_diff = abs(int(source["release_year"]) - int(cand["release_year"]))
            year_sim = max(0.0, 1.0 - year_diff / 15.0)
            rating_bonus = min(1.0, float(cand["rating"]) / 10.0)
            meta_sim = 0.6 * year_sim + 0.4 * rating_bonus

            total_score = (
                self.settings.rec_weight_tropes * trope_sim
                + self.settings.rec_weight_genres * genre_sim
                + self.settings.rec_weight_cast * cast_sim
                + self.settings.rec_weight_meta * meta_sim
            )

            shared_trope_slugs = sorted(
                set(src_tropes.keys()) & set(cand_tropes.keys()),
                key=lambda s: src_tropes[s] + cand_tropes[s],
                reverse=True,
            )
            shared_tropes_ru = [src_trope_names[s] for s in shared_trope_slugs]
            shared_genres_ru = [src_genre_names[s] for s in sorted(src_genres & cand_genres)]

            # Отфильтровываем кандидатов совсем без содержательных пересечений, если есть выбор
            scored.append(
                (
                    cand,
                    total_score,
                    {
                        "shared_tropes": shared_tropes_ru,
                        "shared_genres": shared_genres_ru,
                        "shared_persons": shared_persons,
                        "trope_similarity": round(trope_sim, 3),
                        "genre_similarity": round(genre_sim, 3),
                        "cast_similarity": round(cast_sim, 3),
                    },
                )
            )

        scored.sort(key=lambda item: (item[1], float(item[0]["rating"])), reverse=True)
        top_items = scored[:limit]
        summaries = self.dramas_repo.get_dramas_by_ids([int(x[0]["id"]) for x in top_items])

        recommendations: List[Dict[str, Any]] = []
        for cand, score, explanation in top_items:
            cid = int(cand["id"])
            recommendations.append(
                {
                    "drama": summaries[cid],
                    "similarity_score": round(score, 4),
                    "match_percent": min(99, max(12, round(score * 100))),
                    "explanation": explanation,
                }
            )

        return {
            "source_drama_id": src_id,
            "source_title": source["title_ru"],
            "recommendations": recommendations,
        }
