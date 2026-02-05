from __future__ import annotations

from slotting.algorithms.micro import select_groups
from slotting.algorithms.micro.group_score import group_cost_cycle_volume
from slotting.models import AffinityGroup, SKU


def test_select_groups_dedup_prefers_higher_score_then_rotation() -> None:
    skus = [
        SKU(sku_id="A", rot=10, height=1, volume=1, weight=1, cycle_units=1),
        SKU(sku_id="B", rot=5, height=1, volume=1, weight=1, cycle_units=1),
    ]
    group_low = AffinityGroup(seed_sku_id="A", sku_ids=["A", "B"], score=1.0)
    group_high = AffinityGroup(seed_sku_id="B", sku_ids=["B", "A"], score=2.0)

    selected = select_groups([group_low, group_high], skus)

    assert len(selected) == 1
    assert selected[0].score == 2.0


def test_select_groups_greedy_no_overlap_by_density_then_score() -> None:
    skus = [
        SKU(sku_id="A", rot=10, height=1, volume=2, weight=1, cycle_units=1),
        SKU(sku_id="B", rot=10, height=1, volume=2, weight=1, cycle_units=1),
        SKU(sku_id="C", rot=1, height=1, volume=1, weight=1, cycle_units=1),
    ]
    g1 = AffinityGroup(seed_sku_id="A", sku_ids=["A", "B"], score=10.0)
    g2 = AffinityGroup(seed_sku_id="A", sku_ids=["A", "C"], score=9.0)
    g3 = AffinityGroup(seed_sku_id="B", sku_ids=["B", "C"], score=8.0)

    selected = select_groups([g1, g2, g3], skus, cost_fn=group_cost_cycle_volume)

    assert len(selected) == 1
    assert selected[0].sku_ids == ["A", "C"]


def test_select_groups_default_ignores_cycle_volume_cost() -> None:
    skus = [
        SKU(sku_id="A", rot=10, height=1, volume=2, weight=1, cycle_units=1),
        SKU(sku_id="B", rot=10, height=1, volume=2, weight=1, cycle_units=1),
        SKU(sku_id="C", rot=1, height=1, volume=1, weight=1, cycle_units=1),
    ]
    g1 = AffinityGroup(seed_sku_id="A", sku_ids=["A", "B"], score=10.0)
    g2 = AffinityGroup(seed_sku_id="A", sku_ids=["A", "C"], score=9.0)
    g3 = AffinityGroup(seed_sku_id="B", sku_ids=["B", "C"], score=8.0)

    selected = select_groups([g1, g2, g3], skus)

    assert len(selected) == 1
    assert selected[0].sku_ids == ["A", "B"]


def test_select_groups_cycle_volume_mode_matches_density_ranking() -> None:
    skus = [
        SKU(sku_id="A", rot=10, height=1, volume=2, weight=1, cycle_units=1),
        SKU(sku_id="B", rot=10, height=1, volume=2, weight=1, cycle_units=1),
        SKU(sku_id="C", rot=1, height=1, volume=1, weight=1, cycle_units=1),
    ]
    g1 = AffinityGroup(seed_sku_id="A", sku_ids=["A", "B"], score=10.0)
    g2 = AffinityGroup(seed_sku_id="A", sku_ids=["A", "C"], score=9.0)
    g3 = AffinityGroup(seed_sku_id="B", sku_ids=["B", "C"], score=8.0)

    selected = select_groups([g1, g2, g3], skus, selection_cost_mode="cycle_volume")

    assert len(selected) == 1
    assert selected[0].sku_ids == ["A", "C"]
