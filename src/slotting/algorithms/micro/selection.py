from __future__ import annotations

from collections.abc import Callable, Iterable

from slotting.algorithms.micro.group_score import group_cost_cycle_volume
from slotting.models import AffinityGroup, SKU

CostFunction = Callable[[list[str], dict[str, SKU]], float]


def select_groups(
    groups: Iterable[AffinityGroup],
    skus: Iterable[SKU],
    selection_cost_mode: str = "none",
    cost_fn: CostFunction | None = None,
) -> list[AffinityGroup]:
    """
    Deduplicate and select non-overlapping groups.

    - Dedup keeps the highest score (tie-breaker: rotation).
    - Selection ranks by score by default.
    - Optional cycle-volume mode ranks by value density, then score, then rotation.
    - Result ensures each SKU appears in at most one group.
    """
    sku_list = list(skus)
    sku_by_id = {sku.sku_id: sku for sku in sku_list}
    if selection_cost_mode not in {"none", "cycle_volume"}:
        raise ValueError("selection_cost_mode must be none or cycle_volume")
    if cost_fn is None and selection_cost_mode == "cycle_volume":
        cost_fn = group_cost_cycle_volume

    deduped = _dedupe_groups(groups, sku_by_id)
    ranked = _rank_groups(deduped, sku_by_id, cost_fn)

    selected: list[AffinityGroup] = []
    assigned: set[str] = set()
    for group in ranked:
        if any(sku_id in assigned for sku_id in group.sku_ids):
            continue
        selected.append(group)
        assigned.update(group.sku_ids)

    return selected


def _dedupe_groups(
    groups: Iterable[AffinityGroup],
    sku_by_id: dict[str, SKU],
) -> list[AffinityGroup]:
    by_set: dict[frozenset[str], AffinityGroup] = {}
    rotations: dict[frozenset[str], float] = {}
    for group in groups:
        if not group.sku_ids:
            continue
        if any(sku_id not in sku_by_id for sku_id in group.sku_ids):
            continue
        key = frozenset(group.sku_ids)
        rotation = sum(sku_by_id[sku_id].rot for sku_id in group.sku_ids)
        existing = by_set.get(key)
        if existing is None:
            by_set[key] = group
            rotations[key] = rotation
            continue
        existing_rotation = rotations[key]
        if group.score > existing.score or (
            group.score == existing.score and rotation > existing_rotation
        ):
            by_set[key] = group
            rotations[key] = rotation
    return list(by_set.values())


def _rank_groups(
    groups: Iterable[AffinityGroup],
    sku_by_id: dict[str, SKU],
    cost_fn: CostFunction | None,
) -> list[AffinityGroup]:
    scored: list[tuple[float, float, float, AffinityGroup]] = []
    for group in groups:
        if cost_fn is None:
            primary = group.score
        else:
            cost = cost_fn(group.sku_ids, sku_by_id)
            if cost <= 0:
                primary = 0.0
            else:
                primary = group.score / cost
        rotation = sum(sku_by_id[sku_id].rot for sku_id in group.sku_ids)
        scored.append((primary, group.score, rotation, group))

    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [item[3] for item in scored]
