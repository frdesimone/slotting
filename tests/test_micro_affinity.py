from __future__ import annotations

from slotting.algorithms.micro.affinity_graph import build_affinity_graph
from slotting.algorithms.micro.strategies import JaccardMetric
from slotting.models import Order


def test_build_affinity_graph_jaccard_top_k() -> None:
    orders = [
        Order(order_id="o1", sku_ids=["A", "B"]),
        Order(order_id="o2", sku_ids=["A", "C"]),
        Order(order_id="o3", sku_ids=["A", "B"]),
    ]

    graph = build_affinity_graph(
        orders,
        top_k=1,
        aff_min=0.1,
        metric=JaccardMetric(),
    )

    assert [n.sku_id for n in graph["A"]] == ["B"]
    assert [n.sku_id for n in graph["B"]] == ["A"]
    assert [n.sku_id for n in graph["C"]] == ["A"]
