from __future__ import annotations

from slotting.algorithms.micro import MicroSlottingConfig, build_groups
from slotting.models import Order, SKU


def test_build_groups_greedy_adds_best_candidate() -> None:
    skus = [
        SKU(sku_id="A", rot=1, height=10, volume=1, weight=1),
        SKU(sku_id="B", rot=1, height=10, volume=1, weight=1),
        SKU(sku_id="C", rot=1, height=100, volume=1, weight=1),
    ]

    orders = [Order(order_id=f"ab{i}", sku_ids=["A", "B"]) for i in range(10)]
    orders += [Order(order_id="ac0", sku_ids=["A", "C"])]

    config = MicroSlottingConfig(
        seed_count=1,
        top_k_neighbors=2,
        aff_min=0.0,
        min_delta=0.01,
        max_group_size=3,
        wa=1.0,
        wr=0.0,
        wh=1.0,
        height_ref=0.25,
        p_height=2.0,
    )

    groups = build_groups(skus=skus, orders=orders, config=config)

    assert len(groups) == 1
    assert groups[0].seed_sku_id == "A"
    assert groups[0].sku_ids == ["A", "B"]
