from __future__ import annotations

from slotting.algorithms.micro import MicroSlottingConfig
from slotting.algorithms.micro.kpi_state import build_hybrid_kpi_state
from slotting.algorithms.micro.optimization import LocalSearchConfig, optimize
from slotting.algorithms.micro.step7.allocation import build_trays_for_subgroup
from slotting.models import SKU, Subgroup, Tray


def _build_fixture() -> tuple[list[Subgroup], list[Tray], dict[str, SKU]]:
    skus = [
        SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="B", rot=1, height=12, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="C", rot=1, height=20, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="D", rot=1, height=22, volume=1e-6, weight=1, cycle_units=1),
    ]
    sku_by_id = {sku.sku_id: sku for sku in skus}
    subgroups = [
        Subgroup(subgroup_id="g1-h1", group_id="g1", sku_ids=["A", "B"], score=0.0),
        Subgroup(subgroup_id="g2-h1", group_id="g2", sku_ids=["C", "D"], score=0.0),
    ]
    config = MicroSlottingConfig(unassigned_include=False)
    trays: list[Tray] = []
    for sg in subgroups:
        trays.extend(build_trays_for_subgroup(sg, sku_by_id, config))
    return subgroups, trays, sku_by_id


def test_optimizer_non_decreasing_baseline() -> None:
    subgroups, trays, sku_by_id = _build_fixture()
    affinity_graph = {"A": [], "B": [], "C": [], "D": []}
    config = MicroSlottingConfig(unassigned_include=False)
    state = build_hybrid_kpi_state(subgroups, trays, sku_by_id, affinity_graph, config)
    result = optimize(
        state,
        LocalSearchConfig(iterations=100, seed=42, allow_annealing=False, log_every=0),
    )
    assert result.best_kpi >= result.initial_kpi
