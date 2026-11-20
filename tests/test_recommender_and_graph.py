"""Тесты механизма рекомендаций и построителя графа семантических связей."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_recommendations_provide_xai_explanations(isolated_client: TestClient) -> None:
    dramas = isolated_client.get("/api/dramas", params={"limit": 100}).json()["items"]
    itaewon = next(d for d in dramas if d["slug"] == "itaewon-class")

    resp = isolated_client.get(f"/api/dramas/{itaewon['id']}/recommendations", params={"limit": 5})
    assert resp.status_code == 200
    body = resp.json()

    assert body["source_drama_id"] == itaewon["id"]
    recs = body["recommendations"]
    assert len(recs) == 5
    # Все рекомендованные дорамы не должны совпадать с исходной
    assert all(r["drama"]["id"] != itaewon["id"] for r in recs)
    # Должно присутствовать хотя бы одно содержательное объяснение пересечения
    top = recs[0]
    exp = top["explanation"]
    assert len(exp["shared_tropes"]) + len(exp["shared_genres"]) + len(exp["shared_persons"]) >= 1


def test_knowledge_graph_traversal_and_filters(isolated_client: TestClient) -> None:
    resp = isolated_client.get(
        "/api/graph",
        params={"center_type": "drama", "depth": 2, "include_cast": "true", "include_tropes": "true", "include_genres": "false"},
    )
    assert resp.status_code == 200
    graph = resp.json()

    assert len(graph["nodes"]) > 3
    assert len(graph["edges"]) > 2
    assert graph["stats"]["genres"] == 0
    assert any(n["is_center"] for n in graph["nodes"])
