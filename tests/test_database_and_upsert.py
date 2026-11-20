"""Тесты реляционной схемы (13 таблиц), сидирования и идемпотентности UPSERT."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.connection import get_db_manager
from app.db.schema import TABLE_DESCRIPTIONS
from app.db.seed import seed_initial_database


def test_all_13_tables_exist_and_populated(isolated_client: TestClient) -> None:
    resp = isolated_client.get("/api/overview")
    assert resp.status_code == 200
    data = resp.json()

    assert data["tables_count"] == 13
    returned_names = {t["table_name"] for t in data["tables"]}
    assert returned_names == set(TABLE_DESCRIPTIONS.keys())
    assert data["dramas_count"] >= 30
    assert data["persons_count"] >= 45
    assert data["tropes_count"] >= 20


def test_seed_upsert_does_not_create_duplicates(isolated_client: TestClient) -> None:
    before = isolated_client.get("/api/overview").json()["dramas_count"]
    seed_initial_database(get_db_manager(), force=True)
    after = isolated_client.get("/api/overview").json()["dramas_count"]
    assert before == after


def test_create_drama_and_user_list_crud(isolated_client: TestClient) -> None:
    create_resp = isolated_client.post(
        "/api/dramas",
        json={
            "title_ru": "Ответ 1988",
            "title_en": "Reply 1988",
            "title_kr": "응답하라 1988",
            "release_year": 2015,
            "episodes_count": 20,
            "status": "Completed",
            "rating": 9.3,
            "synopsis_ru": "Тёплая история соседей и друзей на одной улице Сеула.",
            "genre_slugs": ["drama", "slice-of-life"],
            "trope_slugs": ["found-family"],
        },
    )
    assert create_resp.status_code == 201
    drama = create_resp.json()
    assert drama["title_ru"] == "Ответ 1988"

    # Создание пользовательского списка и добавление дорамы
    list_resp = isolated_client.post("/api/lists", json={"name": "Лучшее за всё время"})
    assert list_resp.status_code == 201
    custom_list = list_resp.json()

    upsert_item = isolated_client.put(
        f"/api/lists/{custom_list['id']}/items",
        json={
            "drama_id": drama["id"],
            "personal_rating": 10.0,
            "watched_episodes": 20,
            "notes": "Шедевр о дружбе",
        },
    )
    assert upsert_item.status_code == 200
    assert upsert_item.json()["personal_rating"] == 10.0

    # Удаление элемента и списка
    del_item = isolated_client.delete(f"/api/lists/{custom_list['id']}/items/{drama['id']}")
    assert del_item.status_code == 204
    del_list = isolated_client.delete(f"/api/lists/{custom_list['id']}")
    assert del_list.status_code == 204


def test_years_endpoint_and_year_filter(isolated_client: TestClient) -> None:
    years_resp = isolated_client.get("/api/years")
    assert years_resp.status_code == 200
    years_data = years_resp.json()
    assert len(years_data) >= 5
    assert all("release_year" in row and "dramas_count" in row for row in years_data)

    target_year = years_data[0]["release_year"]
    dramas_resp = isolated_client.get(f"/api/dramas?year={target_year}")
    assert dramas_resp.status_code == 200
    payload = dramas_resp.json()
    assert payload["total"] == years_data[0]["dramas_count"]
    assert all(item["release_year"] == target_year for item in payload["items"])

