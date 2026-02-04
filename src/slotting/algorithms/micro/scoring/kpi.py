from __future__ import annotations

from slotting.algorithms.micro.config import MicroSlottingConfig
from slotting.algorithms.micro.scoring.affinity import pairwise_affinity_sum
from slotting.algorithms.micro.scoring.height import (
    convex_height_penalty,
    height_diff_by_area_for_skus,
)
from slotting.algorithms.micro.scoring.size import size_penalty
from slotting.models import SKU
from slotting.algorithms.micro.strategies import AffinityGraph


def logical_group_kpi(
    sku_ids: list[str],
    sku_by_id: dict[str, SKU],
    affinity_graph: AffinityGraph,
    config: MicroSlottingConfig,
    units_by_sku: dict[str, float],
) -> float:
    if not sku_ids:
        return 0.0
    affinity_total = pairwise_affinity_sum(sku_ids, affinity_graph)
    height_diff = height_diff_by_area_for_skus(sku_ids, sku_by_id, units_by_sku)
    height_penalty = convex_height_penalty(
        height_diff, config.group_height_ref, config.group_height_p
    )
    size_pen = size_penalty(len(sku_ids), config.subgroup_size_gamma, config.subgroup_size_p)
    return affinity_total - config.subgroup_height_weight * height_penalty - size_pen
