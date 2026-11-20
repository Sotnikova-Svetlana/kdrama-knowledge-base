"""Построитель интерактивного графа семантических связей базы знаний.

Формирует подграф вокруг выбранного узла (дорамы, персоны, тропа или жанра)
на глубину 1 или 2 шага с фильтрацией типов рёбер для визуализации на клиенте.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.exceptions import EntityNotFoundError
from app.db.repositories.dramas_repo import DramasRepository


class KnowledgeGraphBuilder:
    """Строит граф знаний (узлы + взвешенные рёбра) из реляционных таблиц."""

    def __init__(self, dramas_repo: Optional[DramasRepository] = None) -> None:
        self.dramas_repo = dramas_repo or DramasRepository()

    def build_subgraph(
        self,
        center_type: str = "drama",
        center_id: Optional[int] = None,
        depth: int = 1,
        include_cast: bool = True,
        include_tropes: bool = True,
        include_genres: bool = True,
        max_nodes: int = 42,
    ) -> Dict[str, Any]:
        """Генерирует подграф связей вокруг центрального объекта БЗ."""
        vectors = self.dramas_repo.get_all_feature_vectors()
        if not vectors:
            return {"center_node_id": "", "nodes": [], "edges": [], "stats": {"nodes": 0, "edges": 0}}

        dramas_by_id = {int(d["id"]): d for d in vectors}

        # Если center_id не задан, берём первую топовую дораму (например, «Итхэвон Класс» / «Гоблин»)
        if center_id is None:
            center_type = "drama"
            center_id = int(vectors[0]["id"])

        center_node_key = f"{center_type}:{center_id}"
        nodes_map: Dict[str, Dict[str, Any]] = {}
        edges_map: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

        def add_node(
            entity_type: str,
            eid: int,
            label: str,
            sublabel: str = "",
            weight: float = 1.0,
        ) -> str:
            nid = f"{entity_type}:{eid}"
            if nid not in nodes_map and len(nodes_map) < max_nodes:
                nodes_map[nid] = {
                    "id": nid,
                    "entity_id": eid,
                    "entity_type": entity_type,
                    "label": label,
                    "sublabel": sublabel,
                    "weight": round(weight, 3),
                    "is_center": nid == center_node_key,
                }
            return nid

        def add_edge(src: str, dst: str, relation: str, weight: float = 1.0) -> None:
            if src not in nodes_map or dst not in nodes_map or src == dst:
                return
            key = (src, dst, relation)
            if key not in edges_map:
                edges_map[key] = {
                    "source": src,
                    "target": dst,
                    "relation": relation,
                    "weight": round(weight, 3),
                }

        def expand_drama(d: Dict[str, Any], expand_neighbors: bool) -> None:
            did = int(d["id"])
            d_nid = add_node(
                "drama",
                did,
                d["title_ru"],
                f"{d['release_year']} · ★ {d['rating']}",
                weight=1.3 if f"drama:{did}" == center_node_key else 1.0,
            )
            if d_nid not in nodes_map:
                return

            if include_tropes:
                for t in d.get("tropes", [])[:6]:
                    t_nid = add_node("trope", int(t["trope_id"]), t["name_ru"], t.get("category", "Троп"), 0.9)
                    add_edge(d_nid, t_nid, "trope", float(t["weight"]))
                    if expand_neighbors and len(nodes_map) < max_nodes:
                        self._link_related_dramas_by_trope(
                            vectors, int(t["trope_id"]), did, t_nid, add_node, add_edge, limit=2
                        )

            if include_cast:
                for c in d.get("cast", [])[:6]:
                    p_nid = add_node("person", int(c["person_id"]), c["name_ru"], c.get("role_type", "Actor"), 0.95)
                    add_edge(d_nid, p_nid, f"cast:{c.get('role_type', 'Main')}", 1.0)
                    if expand_neighbors and len(nodes_map) < max_nodes:
                        self._link_related_dramas_by_person(
                            vectors, int(c["person_id"]), did, p_nid, add_node, add_edge, limit=2
                        )

            if include_genres:
                for g in d.get("genres", [])[:4]:
                    g_nid = add_node("genre", int(g["genre_id"]), g["name_ru"], "Жанр", 0.85)
                    add_edge(d_nid, g_nid, "genre", 0.7)

        if center_type == "drama":
            center_drama = dramas_by_id.get(center_id)
            if not center_drama:
                raise EntityNotFoundError("Дорама для графа", center_id)
            expand_drama(center_drama, expand_neighbors=(depth >= 2))

        elif center_type == "person":
            matched_dramas = [
                d for d in vectors if any(int(c["person_id"]) == center_id for c in d.get("cast", []))
            ]
            if not matched_dramas:
                raise EntityNotFoundError("Персона для графа", center_id)
            first_c = next(c for c in matched_dramas[0]["cast"] if int(c["person_id"]) == center_id)
            p_nid = add_node("person", center_id, first_c["name_ru"], first_c.get("name_en", "Персона"), 1.3)
            for d in matched_dramas[:8]:
                d_nid = add_node("drama", int(d["id"]), d["title_ru"], f"{d['release_year']} · ★ {d['rating']}", 1.05)
                add_edge(d_nid, p_nid, "cast", 1.0)
                if depth >= 2:
                    expand_drama(d, expand_neighbors=False)

        elif center_type == "trope":
            matched_dramas = [
                d for d in vectors if any(int(t["trope_id"]) == center_id for t in d.get("tropes", []))
            ]
            if not matched_dramas:
                raise EntityNotFoundError("Троп для графа", center_id)
            first_t = next(t for t in matched_dramas[0]["tropes"] if int(t["trope_id"]) == center_id)
            t_nid = add_node("trope", center_id, first_t["name_ru"], first_t.get("category", "Троп"), 1.3)
            for d in matched_dramas[:10]:
                t_info = next(t for t in d["tropes"] if int(t["trope_id"]) == center_id)
                d_nid = add_node("drama", int(d["id"]), d["title_ru"], f"{d['release_year']} · ★ {d['rating']}", 1.05)
                add_edge(d_nid, t_nid, "trope", float(t_info["weight"]))
                if depth >= 2:
                    expand_drama(d, expand_neighbors=False)

        else:
            raise EntityNotFoundError("Тип узла графа", center_type)

        nodes = list(nodes_map.values())
        edges = list(edges_map.values())
        return {
            "center_node_id": center_node_key,
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "nodes": len(nodes),
                "edges": len(edges),
                "dramas": sum(1 for n in nodes if n["entity_type"] == "drama"),
                "persons": sum(1 for n in nodes if n["entity_type"] == "person"),
                "tropes": sum(1 for n in nodes if n["entity_type"] == "trope"),
                "genres": sum(1 for n in nodes if n["entity_type"] == "genre"),
            },
        }

    @staticmethod
    def _link_related_dramas_by_trope(
        vectors: List[Dict[str, Any]],
        trope_id: int,
        exclude_drama_id: int,
        trope_nid: str,
        add_node: Any,
        add_edge: Any,
        limit: int = 2,
    ) -> None:
        added = 0
        for cand in vectors:
            cid = int(cand["id"])
            if cid == exclude_drama_id:
                continue
            match = next((t for t in cand.get("tropes", []) if int(t["trope_id"]) == trope_id), None)
            if match:
                d_nid = add_node("drama", cid, cand["title_ru"], f"{cand['release_year']} · ★ {cand['rating']}", 0.9)
                add_edge(d_nid, trope_nid, "trope", float(match["weight"]))
                added += 1
                if added >= limit:
                    break

    @staticmethod
    def _link_related_dramas_by_person(
        vectors: List[Dict[str, Any]],
        person_id: int,
        exclude_drama_id: int,
        person_nid: str,
        add_node: Any,
        add_edge: Any,
        limit: int = 2,
    ) -> None:
        added = 0
        for cand in vectors:
            cid = int(cand["id"])
            if cid == exclude_drama_id:
                continue
            match = next((c for c in cand.get("cast", []) if int(c["person_id"]) == person_id), None)
            if match:
                d_nid = add_node("drama", cid, cand["title_ru"], f"{cand['release_year']} · ★ {cand['rating']}", 0.9)
                add_edge(d_nid, person_nid, f"cast:{match.get('role_type', 'Main')}", 0.9)
                added += 1
                if added >= limit:
                    break
