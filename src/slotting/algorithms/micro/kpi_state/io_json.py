from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slotting.algorithms.micro.config import MicroSlottingConfig
from slotting.algorithms.micro.strategies import AffinityGraph
from slotting.models import AffinityNeighbor, SKU, Subgroup, Tray, TrayItem


def load_affinity_graph_json(path: str | Path) -> AffinityGraph:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    graph: AffinityGraph = {}
    for sku_id, neighbors in data.items():
        graph[sku_id] = [
            AffinityNeighbor(sku_id=item["sku_id"], affinity=float(item["affinity"]))
            for item in neighbors
        ]
    return graph


def dump_affinity_graph_json(path: str | Path, affinity_graph: AffinityGraph) -> None:
    payload = {
        sku_id: [
            {"sku_id": n.sku_id, "affinity": n.affinity} for n in neighbors
        ]
        for sku_id, neighbors in affinity_graph.items()
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def dump_state_to_json(
    path: str | Path,
    config: MicroSlottingConfig,
    sku_by_id: dict[str, SKU],
    affinity_graph: AffinityGraph,
    subgroups: list[Subgroup],
    trays: list[Tray],
) -> None:
    payload: dict[str, Any] = {
        "config": _serialize_config(config),
        "skus": _serialize_skus(sku_by_id),
        "affinity_graph": _serialize_affinity_graph(affinity_graph),
        "subgroups": _serialize_subgroups(subgroups),
        "trays": _serialize_trays(trays),
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_state_from_json(
    path: str | Path,
) -> tuple[MicroSlottingConfig, dict[str, SKU], AffinityGraph, list[Subgroup], list[Tray]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    config = MicroSlottingConfig(**(data.get("config") or {}))
    sku_by_id = _deserialize_skus(data.get("skus", []))
    affinity_graph = _deserialize_affinity_graph(data.get("affinity_graph") or {})
    subgroups = _deserialize_subgroups(data.get("subgroups", []))
    trays = _deserialize_trays(data.get("trays", []))
    return config, sku_by_id, affinity_graph, subgroups, trays


def _serialize_config(config: MicroSlottingConfig) -> dict[str, Any]:
    return {
        key: value
        for key, value in config.__dict__.items()
        if isinstance(value, (int, float, str, bool)) or value is None
    }


def _serialize_skus(sku_by_id: dict[str, SKU]) -> list[dict[str, Any]]:
    return [
        {
            "sku_id": sku.sku_id,
            "rot": sku.rot,
            "height": sku.height,
            "volume": sku.volume,
            "weight": sku.weight,
            "cycle_units": sku.cycle_units,
            "avg_units_per_line": sku.avg_units_per_line,
        }
        for sku in sku_by_id.values()
    ]


def _serialize_affinity_graph(affinity_graph: AffinityGraph) -> dict[str, list[dict[str, Any]]]:
    return {
        sku_id: [
            {"sku_id": n.sku_id, "affinity": n.affinity} for n in neighbors
        ]
        for sku_id, neighbors in affinity_graph.items()
    }


def _serialize_subgroups(subgroups: list[Subgroup]) -> list[dict[str, Any]]:
    return [
        {
            "subgroup_id": sg.subgroup_id,
            "group_id": sg.group_id,
            "sku_ids": sg.sku_ids,
            "score": sg.score,
        }
        for sg in subgroups
    ]


def _serialize_trays(trays: list[Tray]) -> list[dict[str, Any]]:
    return [
        {
            "tray_id": tray.tray_id,
            "group_id": tray.group_id,
            "subgroup_id": tray.subgroup_id,
            "height": tray.height,
            "max_area": tray.max_area,
            "max_weight": tray.max_weight,
            "area_used": tray.area_used,
            "weight_used": tray.weight_used,
            "items": [
                {
                    "sku_id": item.sku_id,
                    "units": item.units,
                    "unit_volume": item.unit_volume,
                    "unit_weight": item.unit_weight,
                    "unit_area": item.unit_area,
                }
                for item in tray.items
            ],
        }
        for tray in trays
    ]


def _deserialize_skus(items: list[dict[str, Any]]) -> dict[str, SKU]:
    return {
        item["sku_id"]: SKU(
            sku_id=item["sku_id"],
            rot=float(item["rot"]),
            height=float(item["height"]),
            volume=float(item["volume"]),
            weight=float(item["weight"]),
            cycle_units=item.get("cycle_units"),
            avg_units_per_line=item.get("avg_units_per_line"),
        )
        for item in items
    }


def _deserialize_affinity_graph(
    graph: dict[str, list[dict[str, Any]]],
) -> AffinityGraph:
    return {
        sku_id: [
            AffinityNeighbor(sku_id=n["sku_id"], affinity=float(n["affinity"]))
            for n in neighbors
        ]
        for sku_id, neighbors in graph.items()
    }


def _deserialize_subgroups(items: list[dict[str, Any]]) -> list[Subgroup]:
    return [
        Subgroup(
            subgroup_id=sg["subgroup_id"],
            group_id=sg["group_id"],
            sku_ids=list(sg["sku_ids"]),
            score=float(sg.get("score", 0.0)),
        )
        for sg in items
    ]


def _deserialize_trays(items: list[dict[str, Any]]) -> list[Tray]:
    trays: list[Tray] = []
    for tray in items:
        tray_items = _deserialize_tray_items(tray.get("items", []))
        trays.append(
            Tray(
                tray_id=tray["tray_id"],
                group_id=tray["group_id"],
                subgroup_id=tray["subgroup_id"],
                height=float(tray["height"]),
                max_area=float(tray["max_area"]),
                max_weight=float(tray["max_weight"]),
                area_used=float(tray["area_used"]),
                weight_used=float(tray["weight_used"]),
                items=tray_items,
            )
        )
    return trays


def _deserialize_tray_items(items: list[dict[str, Any]]) -> list[TrayItem]:
    return [
        TrayItem(
            sku_id=item["sku_id"],
            units=float(item["units"]),
            unit_volume=float(item["unit_volume"]),
            unit_weight=float(item["unit_weight"]),
            total_volume=float(item["units"]) * float(item["unit_volume"]),
            total_weight=float(item["units"]) * float(item["unit_weight"]),
            unit_area=float(item["unit_area"]),
            total_area=float(item["units"]) * float(item["unit_area"]),
        )
        for item in items
    ]
