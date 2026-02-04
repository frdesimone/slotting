from __future__ import annotations

from slotting.algorithms.micro import MicroSlottingConfig
from slotting.algorithms.micro.kpi_state import (
    HybridKpiState,
    PhysicalTrayState,
    RelocateMove,
    build_hybrid_kpi_state,
)
from slotting.algorithms.micro.step7.allocation import build_trays_for_subgroup
from slotting.models import SKU, Subgroup, Tray


def _build_fixture() -> tuple[list[Subgroup], list[Tray], dict[str, SKU]]:
    skus = [
        SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="B", rot=1, height=12, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="C", rot=1, height=20, volume=1e-6, weight=1, cycle_units=1),
    ]
    sku_by_id = {sku.sku_id: sku for sku in skus}
    subgroups = [
        Subgroup(subgroup_id="g1-h1", group_id="g1", sku_ids=["A", "B"], score=0.0),
        Subgroup(subgroup_id="g2-h1", group_id="g2", sku_ids=["C"], score=0.0),
    ]
    config = MicroSlottingConfig(unassigned_include=False)
    trays: list[Tray] = []
    for sg in subgroups:
        trays.extend(build_trays_for_subgroup(sg, sku_by_id, config))
    return subgroups, trays, sku_by_id


def test_physical_preview_rejects_max_trays() -> None:
    subgroups, trays, sku_by_id = _build_fixture()
    affinity_graph = {"A": [], "B": [], "C": []}
    config = MicroSlottingConfig(max_trays=1, unassigned_include=False)
    physical = PhysicalTrayState(
        trays=trays,
        subgroups={sg.subgroup_id: sg for sg in subgroups},
        sku_by_id=sku_by_id,
        config=config,
    )
    # Move B into subgroup with A to increase tray demand; should exceed max_trays=1.
    new_sku_ids = {"g1-h1": ["A", "B", "C"], "g2-h1": []}
    result = physical.preview_subgroup_change(new_sku_ids)
    assert not result.is_valid
    assert any("max_trays_exceeded" in reason for reason in result.reasons)


def test_hybrid_preview_accepts_valid_move() -> None:
    subgroups, trays, sku_by_id = _build_fixture()
    affinity_graph = {"A": [], "B": [], "C": []}
    config = MicroSlottingConfig(unassigned_include=False)
    hybrid = build_hybrid_kpi_state(
        subgroups=subgroups,
        trays=trays,
        sku_by_id=sku_by_id,
        affinity_graph=affinity_graph,
        config=config,
    )
    move = RelocateMove(sku_id="B", from_subgroup_id="g1-h1", to_subgroup_id="g2-h1")
    preview = hybrid.preview_move(move)
    assert preview.is_valid
