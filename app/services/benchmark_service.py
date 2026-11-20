"""Модуль экспериментальной оценки эффективности базы знаний (для защиты курсовой работы).

Проводит воспроизводимые измерения по двум ключевым подсистемам:
1. Fuzzy Search & Layout Correction: точность распознавания (Top-1 Hit Rate),
   доля корректных исправлений опечаток/раскладки и перцентили задержки (p50, p95 мс);
2. Recommendation Engine: Precision@5, Recall@5 и NDCG@5 на экспертной выборке.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.services.recommender import RecommenderService
from app.services.search_engine import FuzzySearchEngine, get_search_engine


def compute_ndcg_at_k(predicted: List[str], relevant: set[str], k: int = 5) -> float:
    """Вычисляет нормализованный дисконтированный кумулятивный выигрыш (NDCG@K)."""
    dcg = 0.0
    for idx, slug in enumerate(predicted[:k], start=1):
        if slug in relevant:
            dcg += 1.0 / math.log2(idx + 1)

    ideal_hits = min(len(relevant), k)
    if ideal_hits == 0:
        return 0.0
    idcg = sum(1.0 / math.log2(idx + 1) for idx in range(1, ideal_hits + 1))
    return round(dcg / idcg, 4) if idcg > 0 else 0.0


class BenchmarkService:
    """Вычисляет количественные метрики качества поиска и рекомендаций."""

    def __init__(
        self,
        search_engine: Optional[FuzzySearchEngine] = None,
        recommender: Optional[RecommenderService] = None,
    ) -> None:
        self.settings = get_settings()
        self.search_engine = search_engine or get_search_engine()
        self.recommender = recommender or RecommenderService()

    def run_full_benchmark(self) -> Dict[str, Any]:
        """Запускает полный цикл экспериментов над текущим состоянием базы знаний."""
        dataset = json.loads(self.settings.offline_dataset_path.read_text(encoding="utf-8"))
        search_cases_raw = dataset.get("benchmark_search_cases", [])
        rec_cases_raw = dataset.get("benchmark_recommendation_cases", [])

        search_results: List[Dict[str, Any]] = []
        latencies: List[float] = []
        passed_count = 0
        by_type_stats: Dict[str, Dict[str, int]] = {}

        for case in search_cases_raw:
            query = case["query"]
            expected = case["expected_slug"]
            case_type = case["case_type"]

            resp = self.search_engine.search(query, limit=5, record_telemetry=False)
            hits = resp["results"]
            top_hit = hits[0] if hits else None
            actual_slug = top_hit["drama"]["slug"] if top_hit else None
            actual_title = top_hit["drama"]["title_ru"] if top_hit else None
            top_score = float(top_hit["score"]) if top_hit else 0.0
            latency = float(resp["latency_ms"])
            passed = actual_slug == expected

            latencies.append(latency)
            if passed:
                passed_count += 1

            bucket = by_type_stats.setdefault(case_type, {"total": 0, "passed": 0})
            bucket["total"] += 1
            if passed:
                bucket["passed"] += 1

            search_results.append(
                {
                    "query": query,
                    "expected_slug": expected,
                    "actual_top_slug": actual_slug,
                    "actual_top_title": actual_title,
                    "case_type": case_type,
                    "correction_kind": resp["correction_kind"],
                    "score": round(top_score, 2),
                    "latency_ms": round(latency, 3),
                    "passed": passed,
                }
            )

        sorted_lat = sorted(latencies)
        total_search = len(search_results)
        p50 = sorted_lat[len(sorted_lat) // 2] if sorted_lat else 0.0
        p95 = sorted_lat[min(len(sorted_lat) - 1, int(len(sorted_lat) * 0.95))] if sorted_lat else 0.0
        avg_lat = sum(sorted_lat) / len(sorted_lat) if sorted_lat else 0.0

        search_summary = {
            "total_cases": total_search,
            "passed_cases": passed_count,
            "accuracy_percent": round((passed_count / total_search) * 100.0, 2) if total_search else 0.0,
            "avg_latency_ms": round(avg_lat, 3),
            "p50_latency_ms": round(p50, 3),
            "p95_latency_ms": round(p95, 3),
            "breakdown_by_type": {
                k: {
                    "total": v["total"],
                    "passed": v["passed"],
                    "accuracy": round((v["passed"] / v["total"]) * 100.0, 1) if v["total"] else 0.0,
                }
                for k, v in by_type_stats.items()
            },
        }

        # Эксперимент для рекомендательной системы
        rec_results: List[Dict[str, Any]] = []
        p5_sum = 0.0
        r5_sum = 0.0
        ndcg_sum = 0.0

        for r_case in rec_cases_raw:
            src_slug = r_case["source_slug"]
            relevant_set = set(r_case["relevant_slugs"])
            rec_resp = self.recommender.get_similar_by_slug(src_slug, limit=5)
            predicted_slugs = [item["drama"]["slug"] for item in rec_resp["recommendations"]]

            hits_k = len(set(predicted_slugs) & relevant_set)
            precision_at_5 = round(hits_k / 5.0, 4)
            recall_at_5 = round(hits_k / max(len(relevant_set), 1), 4)
            ndcg_at_5 = compute_ndcg_at_k(predicted_slugs, relevant_set, k=5)

            p5_sum += precision_at_5
            r5_sum += recall_at_5
            ndcg_sum += ndcg_at_5

            rec_results.append(
                {
                    "source_slug": src_slug,
                    "source_title": rec_resp["source_title"],
                    "predicted_slugs": predicted_slugs,
                    "relevant_slugs": r_case["relevant_slugs"],
                    "precision_at_5": precision_at_5,
                    "recall_at_5": recall_at_5,
                    "ndcg_at_5": ndcg_at_5,
                }
            )

        rec_total = len(rec_results)
        recommendation_summary = {
            "total_cases": rec_total,
            "mean_precision_at_5": round(p5_sum / rec_total, 4) if rec_total else 0.0,
            "mean_recall_at_5": round(r5_sum / rec_total, 4) if rec_total else 0.0,
            "mean_ndcg_at_5": round(ndcg_sum / rec_total, 4) if rec_total else 0.0,
            "weights": {
                "tropes": self.settings.rec_weight_tropes,
                "genres": self.settings.rec_weight_genres,
                "cast": self.settings.rec_weight_cast,
                "meta": self.settings.rec_weight_meta,
            },
        }

        return {
            "search_summary": search_summary,
            "search_cases": search_results,
            "recommendation_summary": recommendation_summary,
            "recommendation_cases": rec_results,
        }
