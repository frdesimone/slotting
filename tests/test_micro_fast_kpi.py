from __future__ import annotations

import pytest

from slotting.algorithms.micro import MicroSlottingConfig
from slotting.algorithms.micro.kpi_state import FastKpiState, RelocateMove, SwapMove
from slotting.algorithms.micro.group_score import estimate_cycle_units
from slotting.algorithms.micro.scoring.kpi import logical_group_kpi
from slotting.models import SKU, Subgroup


def _recompute_global_kpi(
    subgroups: dict[str, Subgroup],
    sku_by_id: dict[str, SKU],
    affinity_graph: dict[str, list],
    config: MicroSlottingConfig,
) -> float:
    units_by_sku = {sku_id: estimate_cycle_units(sku_by_id[sku_id]) for sku_id in sku_by_id}
    return sum(
        logical_group_kpi(sg.sku_ids, sku_by_id, affinity_graph, config, units_by_sku)
        for sg in subgroups.values()
    )


def test_delta_correctness() -> None:
    skus = [
        SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="B", rot=1, height=12, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="C", rot=1, height=20, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="D", rot=1, height=22, volume=1e-6, weight=1, cycle_units=1),
    ]
    sku_by_id = {sku.sku_id: sku for sku in skus}
    affinity_graph = {"A": [], "B": [], "C": [], "D": []}
    config = MicroSlottingConfig(subgroup_max_size=3)

    subgroups = [
        Subgroup(subgroup_id="g1-h1", group_id="g1", sku_ids=["A", "B"], score=0.0),
        Subgroup(subgroup_id="g2-h1", group_id="g2", sku_ids=["C", "D"], score=0.0),
    ]
    state = FastKpiState(subgroups, sku_by_id, affinity_graph, config)
    baseline = _recompute_global_kpi(state.subgroups, sku_by_id, affinity_graph, config)

    preview = state.preview_move(SwapMove(sku_a="A", sku_b="C"))
    assert preview.is_valid
    state.apply_move(SwapMove(sku_a="A", sku_b="C"))

    recomputed = _recompute_global_kpi(state.subgroups, sku_by_id, affinity_graph, config)
    assert (baseline + preview.delta_global_kpi) == pytest.approx(recomputed, rel=1e-6)


def test_constraints_no_empty_trays() -> None:
    skus = [
        SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="B", rot=1, height=12, volume=1e-6, weight=1, cycle_units=1),
    ]
    sku_by_id = {sku.sku_id: sku for sku in skus}
    affinity_graph = {"A": [], "B": []}
    config = MicroSlottingConfig(subgroup_max_size=3)

    subgroups = [
        Subgroup(subgroup_id="g1-h1", group_id="g1", sku_ids=["A"], score=0.0),
        Subgroup(subgroup_id="g2-h1", group_id="g2", sku_ids=["B"], score=0.0),
    ]
    state = FastKpiState(subgroups, sku_by_id, affinity_graph, config)
    preview = state.preview_move(
        RelocateMove(sku_id="A", from_subgroup_id="g1-h1", to_subgroup_id="g2-h1")
    )
    assert not preview.is_valid
    assert "subgroup_cannot_be_empty" in preview.reasons
