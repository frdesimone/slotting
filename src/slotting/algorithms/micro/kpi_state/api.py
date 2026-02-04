from __future__ import annotations

from slotting.algorithms.micro.config import MicroSlottingConfig
from slotting.algorithms.micro.kpi_state.hybrid import HybridKpiState
from slotting.algorithms.micro.kpi_state.physical_eval import PhysicalTrayState
from slotting.algorithms.micro.kpi_state.state import FastKpiState
from slotting.algorithms.micro.strategies import AffinityGraph
from slotting.models import SKU, Subgroup, Tray


def build_hybrid_kpi_state(
    subgroups: list[Subgroup],
    trays: list[Tray],
    sku_by_id: dict[str, SKU],
    affinity_graph: AffinityGraph,
    config: MicroSlottingConfig,
) -> HybridKpiState:
    """Create a hybrid KPI state for optimizer usage (logical + physical)."""
    logical = FastKpiState(
        subgroups=subgroups,
        sku_by_id=sku_by_id,
        affinity_graph=affinity_graph,
        config=config,
    )
    physical = PhysicalTrayState(
        trays=trays,
        subgroups={sg.subgroup_id: sg for sg in subgroups},
        sku_by_id=sku_by_id,
        config=config,
    )
    return HybridKpiState(logical_state=logical, physical_state=physical)
