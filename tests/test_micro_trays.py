from __future__ import annotations

import math

import pytest

from slotting.algorithms.micro import MicroSlottingConfig, build_groups, select_groups
from slotting.algorithms.micro.affinity_graph import build_affinity_graph
from slotting.algorithms.micro.scoring.height import height_diff_by_area_for_skus
from slotting.algorithms.micro.scoring.size import size_penalty, size_penalty_delta
from slotting.algorithms.micro.step7.subgrouping import _subdivide_group
from slotting.algorithms.micro import build_tray_plans
from slotting.models import AffinityGroup, AffinityNeighbor, Order, SKU


def test_size_penalty_delta_convex() -> None:
    config = MicroSlottingConfig(subgroup_size_gamma=0.5, subgroup_size_p=2)
    assert size_penalty(2, config.subgroup_size_gamma, config.subgroup_size_p) == pytest.approx(0.0)
    assert size_penalty(3, config.subgroup_size_gamma, config.subgroup_size_p) == pytest.approx(0.5)
    assert size_penalty_delta(2, config.subgroup_size_gamma, config.subgroup_size_p) == pytest.approx(0.5)


def test_height_penalty_by_area() -> None:
    skus = [
        SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="B", rot=1, height=20, volume=1e-6, weight=1, cycle_units=1),
    ]
    sku_by_id = {sku.sku_id: sku for sku in skus}
    units_by_sku = {sku.sku_id: 1.0 for sku in skus}
    penalty = height_diff_by_area_for_skus(["A", "B"], sku_by_id, units_by_sku)
    # avg_height = total_volume / total_area = 2000 / 150 = 13.333..., max=20
    assert penalty == pytest.approx(6.6666666667, rel=1e-6)


def test_subgrouping_respects_max_size_and_delta_stop() -> None:
    skus = [
        SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="B", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="C", rot=1, height=100, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="D", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1),
    ]
    sku_by_id = {sku.sku_id: sku for sku in skus}
    affinity_graph = {
        "A": [AffinityNeighbor(sku_id="B", affinity=1.0)],
        "B": [AffinityNeighbor(sku_id="A", affinity=1.0)],
    }
    group = AffinityGroup(seed_sku_id="A", sku_ids=["A", "B", "C", "D"], score=1.0)
    config = MicroSlottingConfig(
        subgroup_max_size=3,
        subgroup_height_weight=0.1,
        subgroup_size_gamma=0.1,
        subgroup_seed_pairs_cap=20,
        subgroup_candidate_eval_cap=10,
        subgroup_allow_singleton=True,
        subgroup_singleton_strategy="allow_singleton",
    )

    subgroups = _subdivide_group(
        group=group,
        sku_by_id=sku_by_id,
        affinity_graph=affinity_graph,
        config=config,
    )

    assert all(len(sg.sku_ids) <= config.subgroup_max_size for sg in subgroups)
    assert any("A" in sg.sku_ids and "B" in sg.sku_ids for sg in subgroups)


def test_tray_count_uses_op_void_area() -> None:
    # SKU A: volume=1e-6 m³, height=10 mm (no width/length)
    # unit_area = volume_mm3 / height_mm = (1e-6 * 1e9) / (10 * 10) = 1000 / 100 = 10 mm²
    # tray_base_area_max=1000, tray_op_void=0.1 => max_area = 900 mm²
    # cycle_units=100 => total_area = 100 * 10 = 1000 mm² > 900 → forces 2 trays
    skus = [
        SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=100),
    ]
    group = AffinityGroup(seed_sku_id="A", sku_ids=["A"], score=1.0)
    affinity_graph = {"A": []}
    config = MicroSlottingConfig(
        subgroup_allow_singleton=True,
        subgroup_singleton_strategy="allow_singleton",
        tray_base_area_max=1000.0,
        tray_weight_max=1000.0,
        tray_op_void=0.1,
        unassigned_include=False,
    )
    plans = build_tray_plans(
        selected_groups=[group],
        skus=skus,
        affinity_graph=affinity_graph,
        config=config,
    )
    trays = plans[0].trays
    assert len(trays) == 2


def test_tray_allocation_deterministic_and_within_capacity() -> None:
    skus = [
        SKU(sku_id="B", rot=1, height=20, volume=2e-6, weight=1, cycle_units=5),
        SKU(sku_id="A", rot=1, height=30, volume=3e-6, weight=1, cycle_units=5),
    ]
    group = AffinityGroup(seed_sku_id="A", sku_ids=["A", "B"], score=1.0)
    affinity_graph = {"A": [], "B": []}
    config = MicroSlottingConfig(
        subgroup_allow_singleton=True,
        subgroup_singleton_strategy="allow_singleton",
        tray_base_area_max=2000.0,
        tray_weight_max=100.0,
        tray_op_void=0.0,
        unassigned_include=False,
    )

    plans = build_tray_plans(
        selected_groups=[group],
        skus=skus,
        affinity_graph=affinity_graph,
        config=config,
    )
    trays = plans[0].trays

    for tray in trays:
        assert tray.area_used <= tray.max_area + 1e-6
        assert tray.weight_used <= tray.max_weight + 1e-6
        if tray.items:
            heights = [sku.height for sku in skus if sku.sku_id in {i.sku_id for i in tray.items}]
            assert tray.height == max(heights)


def test_integration_steps_0_to_7_outputs_trays() -> None:
    skus = [
        SKU(sku_id="A", rot=10, height=10, volume=1e-6, weight=1, cycle_units=10),
        SKU(sku_id="B", rot=8, height=10, volume=1e-6, weight=1, cycle_units=8),
        SKU(sku_id="C", rot=5, height=10, volume=1e-6, weight=1, cycle_units=5),
    ]
    orders = [
        Order(order_id="o1", sku_ids=["A", "B"]),
        Order(order_id="o2", sku_ids=["A", "C"]),
        Order(order_id="o3", sku_ids=["A", "B"]),
    ]
    config = MicroSlottingConfig(
        group_seed_count=1,
        graph_top_k_neighbors=2,
        graph_aff_min=0.0,
        group_min_delta=0.0,
        group_max_size=3,
        group_score_wa=1.0,
        group_score_wr=0.0,
        group_score_wh=0.0,
        subgroup_allow_singleton=True,
        subgroup_singleton_strategy="allow_singleton",
        unassigned_include=False,
    )

    affinity_graph = build_affinity_graph(
        orders=orders,
        top_k=config.graph_top_k_neighbors,
        aff_min=config.graph_aff_min,
        metric=config.affinity_metric,
    )
    groups = build_groups(skus=skus, orders=orders, config=config)
    selected_groups = select_groups(groups=groups, skus=skus)
    plans = build_tray_plans(
        selected_groups=selected_groups,
        skus=skus,
        affinity_graph=affinity_graph,
        config=config,
    )
    assert plans
    trays = [tray for plan in plans for tray in plan.trays]
    assert trays
    for tray in trays:
        assert tray.tray_id
        assert tray.group_id
        assert tray.subgroup_id
        assert tray.area_used <= tray.max_area + 1e-6
        assert tray.weight_used <= tray.max_weight + 1e-6


def test_unassigned_skus_packed_by_height_and_affinity() -> None:
    skus = [
        SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="B", rot=1, height=11, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="C", rot=1, height=50, volume=1e-6, weight=1, cycle_units=1),
    ]
    affinity_graph = {
        "A": [AffinityNeighbor(sku_id="B", affinity=1.0)],
        "B": [AffinityNeighbor(sku_id="A", affinity=1.0)],
        "C": [],
    }
    config = MicroSlottingConfig(
        unassigned_include=True,
        unassigned_height_delta_max=5.0,
        tray_base_area_max=1e9,
        tray_weight_max=1000.0,
    )

    plans = build_tray_plans(
        selected_groups=[],
        skus=skus,
        affinity_graph=affinity_graph,
        config=config,
    )
    assert len(plans) == 1
    subgroups = plans[0].subgroups
    assert any(set(sg.sku_ids) == {"A", "B"} for sg in subgroups)
    assert any(sg.sku_ids == ["C"] for sg in subgroups)
