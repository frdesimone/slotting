from __future__ import annotations

import json
from typing import Iterable

from slotting.algorithms.micro.scoring.affinity import pairwise_affinity_sum
from slotting.algorithms.micro.scoring.height import height_diff_by_area_for_tray
from slotting.algorithms.micro.strategies import AffinityGraph
from slotting.models import SKU, Tray


def trays_to_csv_rows(
    trays: Iterable[Tray],
    sku_by_id: dict[str, SKU],
    affinity_graph: AffinityGraph,
) -> list[list[str]]:
    """Build CSV rows with per-tray stats and compact item payload."""
    rows = [
        [
            "tray_id",
            "group_id",
            "subgroup_id",
            "sku_count",
            "area_used",
            "area_waste",
            "area_waste_pct",
            "weight_used",
            "max_height",
            "height_waste",
            "height_waste_pct",
            "affinity_sum",
            "tray_area_capacity",
            "tray_weight_capacity",
            "items_json",
        ]
    ]
    for tray in trays:
        items: dict[str, float] = {}
        for item in tray.items:
            items[item.sku_id] = items.get(item.sku_id, 0.0) + float(item.units)
        area_waste = max(tray.max_area - tray.area_used, 0.0)
        area_waste_pct = (area_waste / tray.max_area * 100.0) if tray.max_area > 0 else 0.0
        height_waste = max(height_diff_by_area_for_tray(tray), 0.0)
        height_waste_pct = (height_waste / tray.height * 100.0) if tray.height > 0 else 0.0
        sku_ids = list(items.keys())
        affinity_sum = pairwise_affinity_sum(sku_ids, affinity_graph)
        rows.append(
            [
                tray.tray_id,
                tray.group_id,
                tray.subgroup_id,
                str(len(items)),
                f"{tray.area_used:.6f}",
                f"{area_waste:.6f}",
                f"{area_waste_pct:.2f}",
                f"{tray.weight_used:.6f}",
                f"{tray.height:.6f}",
                f"{height_waste:.6f}",
                f"{height_waste_pct:.2f}",
                f"{affinity_sum:.6f}",
                f"{tray.max_area:.6f}",
                f"{tray.max_weight:.6f}",
                json.dumps(items, sort_keys=True),
            ]
        )
    return rows
