"""Тесты автотеггера тропов, автономного обновления (оффлайн дельта) и лаборатории бенчмарков."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.auto_tagger import TropeAutoTagger


def test_auto_tagger_extracts_tropes_from_synopsis(isolated_client: TestClient) -> None:
    tagger = TropeAutoTagger()
    extracted = tagger.extract_tropes(
        synopsis_ru="Гениальный прокурор расследует коррупцию элиты и охотится на серийного убийцу, используя тайную личность и месть."
    )
    slugs = {item.slug for item in extracted}
    assert "corrupt-elites" in slugs
    assert "serial-killer-hunt" in slugs
    assert "revenge-mastermind" in slugs


def test_offline_sync_upserts_without_duplicates_and_updates_ongoing(isolated_client: TestClient) -> None:
    before_overview = isolated_client.get("/api/overview").json()
    before_count = before_overview["dramas_count"]

    sync_resp = isolated_client.post("/api/sync/run", json={"mode": "offline"})
    assert sync_resp.status_code == 200
    sync_data = sync_resp.json()

    assert sync_data["status"] == "completed"
    assert sync_data["dramas_added"] >= 4
    assert sync_data["dramas_updated"] >= 1
    assert sync_data["tropes_assigned"] >= 5

    after_overview = isolated_client.get("/api/overview").json()
    assert after_overview["dramas_count"] == before_count + sync_data["dramas_added"]

    # Повторный прогон того же дельта-пакета не должен создавать дублей
    second_resp = isolated_client.post("/api/sync/run", json={"mode": "offline"}).json()
    assert second_resp["dramas_added"] == 0


def test_benchmark_suite_metrics(isolated_client: TestClient) -> None:
    resp = isolated_client.get("/api/benchmark")
    assert resp.status_code == 200
    data = resp.json()

    assert data["search_summary"]["total_cases"] >= 25
    assert data["search_summary"]["accuracy_percent"] >= 85.0
    assert data["recommendation_summary"]["total_cases"] >= 6
    assert data["recommendation_summary"]["mean_ndcg_at_5"] > 0.4


def test_upsert_by_tmdb_id_with_different_slug_has_no_unique_error(isolated_client: TestClient) -> None:
    from app.db.connection import get_db_manager
    from app.db.seed import upsert_drama_bundle

    db = get_db_manager()
    with db.write_session() as conn:
        drama_id, action = upsert_drama_bundle(
            conn,
            {
                "tmdb_id": 96162,  # itaewon-class
                "slug": "tmdb-96162-alt",
                "title_ru": "Итхэвон Класс",
                "title_en": "Itaewon Class",
                "release_year": 2020,
                "episodes_count": 16,
                "status": "Completed",
                "rating": 8.6,
                "genres": [],
                "platforms": [],
                "tropes": [],
                "cast": [],
            },
            {"genres": {}, "platforms": {}, "tropes": {}, "persons": {}},
        )
    assert drama_id > 0
    assert action in ("updated", "unchanged")


def test_roman_to_russian_transliterates_korean_names() -> None:
    from app.services.sync_service import roman_to_russian

    assert roman_to_russian("Park Bo-young") == "Пак Бо Ён"
    assert roman_to_russian("Kim Hye-yoon") == "Ким Хе Юн"
    assert roman_to_russian("Byeon Woo-seok") == "Пён У Сок"
    assert roman_to_russian("Jung Hae-in") == "Чон Хэ Ин"
    assert roman_to_russian("Пак Со Джун") == "Пак Со Джун"
    assert roman_to_russian("노상현") == "Но Санхён"


def test_tmdb_discover_paginates_past_existing_ids() -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from app.services.sync_service import SyncOrchestrator

    orch = SyncOrchestrator()

    page_1_payload = {
        "total_pages": 3,
        "results": [
            {"id": 101, "poster_path": "/p1.jpg", "overview": "Already in DB"},
            {"id": 102, "poster_path": "/p2.jpg", "overview": "Already in DB"},
        ],
    }
    page_2_payload = {
        "total_pages": 3,
        "results": [
            {"id": 103, "poster_path": None, "overview": "No poster"},
            {"id": 201, "poster_path": "/p201.jpg", "overview": "Fresh drama 1"},
            {"id": 202, "poster_path": "/p202.jpg", "overview": "Fresh drama 2"},
        ],
    }

    async def fake_get(url: str, params=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = page_1_payload if params["page"] == 1 else page_2_payload
        return resp

    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=fake_get)

    picked = asyncio.run(
        orch._discover_unseen_tmdb_ids(
            client=fake_client,
            api_key="test-key",
            existing_tmdb_ids={101, 102},
            limit_new=2,
            max_pages=3,
        )
    )
    assert picked == [201, 202]


