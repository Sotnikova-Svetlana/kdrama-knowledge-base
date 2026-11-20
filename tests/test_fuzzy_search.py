"""Тесты интеллектуального поиска Fuzzy Search, коррекции раскладки EN<->RU и автоподсказок."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.search_engine import convert_en_to_ru, convert_ru_to_en


def test_keyboard_layout_converters() -> None:
    assert convert_en_to_ru("uj,kby") == "гоблин"
    assert convert_en_to_ru("Rjhjktdf ck`p") == "Королева слёз"
    assert convert_ru_to_en("Слава") == "Ckfdf"


def test_fuzzy_search_corrects_typos_and_returns_banner(isolated_client: TestClient) -> None:
    resp = isolated_client.get("/api/search", params={"q": "Итевон Клас"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["was_corrected"] is True
    assert body["correction_kind"] == "typo"
    assert "Итхэвон Класс" in (body["banner_message"] or "")
    assert body["results"][0]["drama"]["slug"] == "itaewon-class"


def test_fuzzy_search_corrects_wrong_keyboard_layout(isolated_client: TestClient) -> None:
    for query, expected_slug in [
        ("Rjhjktdf ck`p", "queen-of-tears"),
        ("Bn[tdjy Rkfcc", "itaewon-class"),
        ("uj,kby", "goblin"),
    ]:
        resp = isolated_client.get("/api/search", params={"q": query})
        assert resp.status_code == 200
        body = resp.json()
        assert body["was_corrected"] is True
        assert body["correction_kind"] in ("layout", "layout_and_typo")
        assert body["results"][0]["drama"]["slug"] == expected_slug


def test_autocomplete_grouped_entities(isolated_client: TestClient) -> None:
    resp = isolated_client.get("/api/search/autocomplete", params={"q": "Пак"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) >= 1
    assert any(item["entity_type"] in ("person", "drama") for item in body["items"])
