from __future__ import annotations

from slotting.algorithms.micro.strategies import _lookup_affinity, AffinityGraph


def pairwise_affinity_sum(
    sku_ids: list[str],
    affinity_graph: AffinityGraph,
) -> float:
    if not sku_ids:
        return 0.0
    affinity_total = 0.0
    for idx, sku_id in enumerate(sku_ids):
        for other_id in sku_ids[idx + 1 :]:
            affinity_total += _lookup_affinity(sku_id, other_id, affinity_graph)
    return affinity_total
