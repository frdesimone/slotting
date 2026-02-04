from __future__ import annotations

import math

from slotting.algorithms.micro.config import MicroSlottingConfig
from slotting.algorithms.micro.scoring.height import (
    convex_height_penalty,
    height_diff_by_area_for_skus,
)
from slotting.algorithms.micro.strategies import AffinityGraph
from slotting.models import SKU


def group_score(
    seed_id: str,
    group_ids: list[str],
    sku_by_id: dict[str, SKU],
    affinity_graph: AffinityGraph,
    config: MicroSlottingConfig,
) -> float:
    affinity = config.affinity_scorer.score(
        seed_id=seed_id,
        group_ids=group_ids,
        affinity_graph=affinity_graph,
    )
    rotation = _rotation_benefit(group_ids, sku_by_id)
    units_by_sku = {sku_id: estimate_cycle_units(sku_by_id[sku_id]) for sku_id in group_ids}
    height_diff = height_diff_by_area_for_skus(group_ids, sku_by_id, units_by_sku)
    height_penalty = convex_height_penalty(
        height_diff, config.group_height_ref, config.group_height_p
    )

    return (
        config.group_score_wa * affinity
        + config.group_score_wr * rotation
        - config.group_score_wh * height_penalty
    )


def estimate_cycle_units(sku: SKU) -> float:
    units: float
    if sku.cycle_units is not None:
        units = sku.cycle_units
    elif sku.avg_units_per_line is not None:
        units = sku.rot * sku.avg_units_per_line
    else:
        units = sku.rot
    return float(math.ceil(units))


def group_cost_cycle_volume(group_ids: list[str], sku_by_id: dict[str, SKU]) -> float:
    return sum(
        estimate_cycle_units(sku_by_id[sku_id]) * sku_by_id[sku_id].volume
        for sku_id in group_ids
    )


def _rotation_benefit(group_ids: list[str], sku_by_id: dict[str, SKU]) -> float:
    return sum(sku_by_id[sku_id].rot for sku_id in group_ids)
