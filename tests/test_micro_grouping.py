from __future__ import annotations

from slotting.algorithms.micro import MicroSlottingConfig, build_groups
from slotting.models import Order, SKU


def test_build_groups_greedy_adds_best_candidate() -> None:
    skus = [
        SKU(sku_id="A", rot=1, height=10, volume=1, weight=1),
        SKU(sku_id="B", rot=1, height=10, volume=1, weight=1),
        SKU(sku_id="C", rot=1, height=10, volume=1, weight=1),
    ]

    orders = [Order(order_id=f"ab{i}", sku_ids=["A", "B"]) for i in range(10)]
    orders += [Order(order_id="ac0", sku_ids=["A", "C"])]

    config = MicroSlottingConfig(
        group_seed_count=1,
        graph_top_k_neighbors=2,
        graph_aff_min=0.0,
        group_min_delta=0.01,
        group_max_size=3,
        group_score_wa=1.0,
        group_score_wr=0.0,
        group_score_wh=1.0,
        group_height_ref=0.25,
        group_height_p=2.0,
    )

    groups = build_groups(skus=skus, orders=orders, config=config)

    assert len(groups) == 1
    assert groups[0].seed_sku_id == "C"
    assert groups[0].sku_ids == ["C", "A"]
