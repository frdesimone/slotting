from __future__ import annotations

from slotting.algorithms.micro.config import MicroSlottingConfig
from slotting.models import SKU


def group_score(
    seed_id: str,
    group_ids: list[str],
    sku_by_id: dict[str, SKU],
    affinity_graph: dict[str, list],
    config: MicroSlottingConfig,
) -> float:
    affinity = config.affinity_scorer.score(
        seed_id=seed_id,
        group_ids=group_ids,
        affinity_graph=affinity_graph,
    )
    rotation = _rotation_benefit(group_ids, sku_by_id)
    height_penalty = _height_penalty(group_ids, sku_by_id, config)

    return (
        config.wa * affinity
        + config.wr * rotation
        - config.wh * height_penalty
    )


def estimate_cycle_units(sku: SKU) -> float:
    if sku.cycle_units is not None:
        return sku.cycle_units
    if sku.avg_units_per_line is not None:
        return sku.rot * sku.avg_units_per_line
    return sku.rot


def group_cost_cycle_volume(group_ids: list[str], sku_by_id: dict[str, SKU]) -> float:
    return sum(
        estimate_cycle_units(sku_by_id[sku_id]) * sku_by_id[sku_id].volume
        for sku_id in group_ids
    )


def _rotation_benefit(group_ids: list[str], sku_by_id: dict[str, SKU]) -> float:
    return sum(sku_by_id[sku_id].rot for sku_id in group_ids)


def _height_penalty(
    group_ids: list[str],
    sku_by_id: dict[str, SKU],
    config: MicroSlottingConfig,
) -> float:
    heights = [sku_by_id[sku_id].height for sku_id in group_ids]
    h_max = max(heights)

    weights = [sku_by_id[sku_id].rot for sku_id in group_ids]
    weight_sum = sum(weights)
    if weight_sum <= 0:
        h_avg = sum(heights) / len(heights)
    else:
        h_avg = sum(h * w for h, w in zip(heights, weights)) / weight_sum

    waste_ratio = (h_max - h_avg) / max(h_max, 1e-9)
    return (waste_ratio / max(config.height_ref, 1e-9)) ** config.p_height
