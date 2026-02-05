from __future__ import annotations

from typing import Iterable

from slotting.algorithms.micro.config import MicroSlottingConfig
from slotting.algorithms.micro.strategies import AffinityGraph
from slotting.models import AffinityGroup, SKU, TrayPlan
from .subgrouping import _build_unassigned_subgroups, _subdivide_group
from .allocation import build_trays_for_subgroup
from .csv_export import trays_to_csv_rows


def build_tray_plans(
    selected_groups: Iterable[AffinityGroup],
    skus: Iterable[SKU],
    affinity_graph: AffinityGraph,
    config: MicroSlottingConfig,
) -> list[TrayPlan]:
    """Build Step 7 tray plans for the selected groups and optional unassigned SKUs."""
    sku_list = list(skus)
    sku_by_id = {sku.sku_id: sku for sku in sku_list}
    plans: list[TrayPlan] = []
    assigned_skus: set[str] = set()
    total_trays = 0
    for group in selected_groups:
        subgroups = _subdivide_group(
            group=group,
            sku_by_id=sku_by_id,
            affinity_graph=affinity_graph,
            config=config,
        )
        for subgroup in subgroups:
            assigned_skus.update(subgroup.sku_ids)
        trays: list = []
        for subgroup in subgroups:
            remaining = config.max_trays - total_trays
            if remaining <= 0:
                raise ValueError(
                    f"Reached max_trays={config.max_trays} before subgroup "
                    f"{subgroup.subgroup_id} (allocated={total_trays})"
                )
            subgroup_trays = build_trays_for_subgroup(
                subgroup, sku_by_id, config, max_trays_limit=remaining
            )
            trays.extend(subgroup_trays)
            total_trays += len(subgroup_trays)
        plans.append(TrayPlan(group_id=group.seed_sku_id, subgroups=subgroups, trays=trays))

    if config.unassigned_include:
        unassigned_ids = sorted({sku.sku_id for sku in sku_list} - assigned_skus)
        if unassigned_ids:
            extra_subgroups = _build_unassigned_subgroups(
                unassigned_ids=unassigned_ids,
                sku_by_id=sku_by_id,
                affinity_graph=affinity_graph,
                config=config,
            )
            extra_trays: list = []
            for subgroup in extra_subgroups:
                remaining = config.max_trays - total_trays
                if remaining <= 0:
                    raise ValueError(
                        f"Reached max_trays={config.max_trays} before subgroup "
                        f"{subgroup.subgroup_id} (allocated={total_trays})"
                    )
                subgroup_trays = build_trays_for_subgroup(
                    subgroup, sku_by_id, config, max_trays_limit=remaining
                )
                extra_trays.extend(subgroup_trays)
                total_trays += len(subgroup_trays)
            plans.append(
                TrayPlan(
                    group_id="unassigned",
                    subgroups=extra_subgroups,
                    trays=extra_trays,
                )
            )

    return plans

__all__ = ["build_tray_plans", "trays_to_csv_rows"]
