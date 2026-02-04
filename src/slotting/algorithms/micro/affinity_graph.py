from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Iterable

from slotting.models import AffinityNeighbor, Order
from slotting.algorithms.micro.strategies import AffinityMetric, AffinityGraph

OrdersWith = dict[str, int]
OrdersWithBoth = dict[tuple[str, str], int]


def build_affinity_graph(
    orders: Iterable[Order],
    top_k: int,
    aff_min: float,
    metric: AffinityMetric,
) -> AffinityGraph:
    """
    Build a sparse affinity graph using per-order SKU co-occurrence.

    Notes:
    - Co-occurrence uses the set of SKUs per order (no repeated lines per order).
    - Each SKU keeps only its top-K neighbors by affinity.
    """
    orders_with, orders_with_both = _count_cooccurrences(orders)
    neighbors = _build_neighbors(
        orders_with=orders_with,
        orders_with_both=orders_with_both,
        aff_min=aff_min,
        metric=metric,
    )
    return _prune_neighbors(neighbors, top_k=top_k)


def _count_cooccurrences(
    orders: Iterable[Order],
) -> tuple[OrdersWith, OrdersWithBoth]:
    orders_with: OrdersWith = defaultdict(int)
    orders_with_both: OrdersWithBoth = defaultdict(int)

    for order in orders:
        sku_set = set(order.sku_ids)
        for sku_id in sku_set:
            orders_with[sku_id] += 1
        for a, b in combinations(sorted(sku_set), 2):
            orders_with_both[(a, b)] += 1

    return orders_with, orders_with_both


def _build_neighbors(
    orders_with: OrdersWith,
    orders_with_both: OrdersWithBoth,
    aff_min: float,
    metric: AffinityMetric,
) -> AffinityGraph:
    neighbors: AffinityGraph = defaultdict(list)
    for (a, b), both in orders_with_both.items():
        with_a = orders_with[a]
        with_b = orders_with[b]
        affinity = metric.compute(with_a, with_b, both)
        if affinity is None:
            continue
        if affinity < aff_min:
            continue
        neighbors[a].append(AffinityNeighbor(sku_id=b, affinity=affinity))
        neighbors[b].append(AffinityNeighbor(sku_id=a, affinity=affinity))
    return neighbors


def _prune_neighbors(
    neighbors: AffinityGraph,
    top_k: int,
) -> AffinityGraph:
    pruned: AffinityGraph = {}
    for sku_id, neighs in neighbors.items():
        neighs_sorted = sorted(neighs, key=lambda n: n.affinity, reverse=True)
        pruned[sku_id] = neighs_sorted[:top_k]
    return pruned
