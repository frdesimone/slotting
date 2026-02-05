from __future__ import annotations

from slotting.algorithms.micro.config import MicroSlottingConfig
from slotting.algorithms.micro.group_score import estimate_cycle_units
from slotting.algorithms.micro.scoring.kpi import logical_group_kpi
from slotting.algorithms.micro.step7.allocation import build_trays_for_subgroup
from slotting.algorithms.micro.strategies import _lookup_affinity, AffinityGraph
from slotting.algorithms.micro.utils import cycle_area_weight, tray_capacity
from slotting.models import AffinityGroup, SKU, Subgroup


def _subdivide_group(
    group: AffinityGroup,
    sku_by_id: dict[str, SKU],
    affinity_graph: AffinityGraph,
    config: MicroSlottingConfig,
) -> list[Subgroup]:
    """Split a logical group into subgroups using greedy growth from seed pairs."""
    max_size = min(config.subgroup_max_size, config.group_max_size)
    units_by_sku = _units_by_sku(group.sku_ids, sku_by_id)
    physical_penalty_cache: dict[tuple[str, ...], float] = {}
    remaining = sorted(group.sku_ids)
    remaining_set = set(remaining)
    subgroups: list[Subgroup] = []
    subgroup_index = 1

    while len(remaining_set) >= 2:
        best = _select_best_seed_subgroup(
            remaining_set=remaining_set,
            sku_by_id=sku_by_id,
            affinity_graph=affinity_graph,
            config=config,
            max_size=max_size,
            units_by_sku=units_by_sku,
            physical_penalty_cache=physical_penalty_cache,
        )
        if best is None:
            break
        subgroup_ids, score = best
        _append_subgroup(
            subgroups=subgroups,
            subgroup_id=f"{group.seed_sku_id}-h{subgroup_index}",
            group_id=group.seed_sku_id,
            sku_ids=subgroup_ids,
            score=score,
        )
        subgroup_index += 1
        remaining_set.difference_update(subgroup_ids)

    if remaining_set:
        remaining_list = sorted(remaining_set)
        _handle_remaining_skus(
            remaining_list=remaining_list,
            group_id=group.seed_sku_id,
            subgroups=subgroups,
            sku_by_id=sku_by_id,
            affinity_graph=affinity_graph,
            config=config,
            next_index=subgroup_index,
            max_size=max_size,
            units_by_sku=units_by_sku,
            physical_penalty_cache=physical_penalty_cache,
        )

    return subgroups


def _select_seed_pairs(
    remaining_set: set[str],
    affinity_graph: AffinityGraph,
    config: MicroSlottingConfig,
) -> list[tuple[str, str, float]]:
    """Return top affinity pairs among remaining SKUs, capped by config."""
    pairs: list[tuple[str, str, float]] = []
    remaining_sorted = sorted(remaining_set)
    remaining_lookup = set(remaining_sorted)
    for sku_id in remaining_sorted:
        for neighbor in affinity_graph.get(sku_id, []):
            if neighbor.sku_id not in remaining_lookup:
                continue
            if sku_id >= neighbor.sku_id:
                continue
            pairs.append((sku_id, neighbor.sku_id, neighbor.affinity))

    pairs.sort(key=lambda item: (-item[2], item[0], item[1]))
    cap = config.subgroup_seed_pairs_cap
    if cap <= 0:
        return pairs
    return pairs[: min(cap, len(pairs))]


def _grow_subgroup_from_pair(
    a: str,
    b: str,
    remaining_set: set[str],
    sku_by_id: dict[str, SKU],
    affinity_graph: AffinityGraph,
    config: MicroSlottingConfig,
    max_size: int,
    units_by_sku: dict[str, float],
    physical_penalty_cache: dict[tuple[str, ...], float],
) -> tuple[list[str], float, float]:
    """Greedy expansion from a pair using marginal score deltas."""
    subgroup_ids = [a, b]
    subgroup_ids.sort()
    logical_score = logical_group_kpi(
        subgroup_ids, sku_by_id, affinity_graph, config, units_by_sku
    )
    physical_penalty = _subgroup_physical_penalty(
        subgroup_ids, sku_by_id, config, physical_penalty_cache
    )
    total_score = logical_score - physical_penalty

    while len(subgroup_ids) < max_size:
        candidates = sorted(remaining_set.difference(subgroup_ids))
        if not candidates:
            break

        cap = config.subgroup_candidate_eval_cap
        if 0 < cap < len(candidates):
            candidates = _top_candidates_by_affinity(
                candidates, subgroup_ids, affinity_graph, cap
            )

        best_delta: float | None = None
        best_candidate: str | None = None
        best_logical_score: float | None = None
        best_physical_penalty: float | None = None
        best_total_score: float | None = None

        for candidate in candidates:
            candidate_ids = sorted(subgroup_ids + [candidate])
            candidate_logical_score = logical_group_kpi(
                candidate_ids, sku_by_id, affinity_graph, config, units_by_sku
            )
            candidate_physical_penalty = _subgroup_physical_penalty(
                candidate_ids, sku_by_id, config, physical_penalty_cache
            )
            candidate_total_score = (
                candidate_logical_score - candidate_physical_penalty
            )
            delta = candidate_total_score - total_score

            if best_delta is None or delta > best_delta or (
                delta == best_delta and candidate < (best_candidate or "")
            ):
                best_delta = delta
                best_candidate = candidate
                best_logical_score = candidate_logical_score
                best_physical_penalty = candidate_physical_penalty
                best_total_score = candidate_total_score

        if (
            best_delta is None
            or best_delta <= config.subgroup_min_delta
            or best_candidate is None
            or best_logical_score is None
            or best_physical_penalty is None
            or best_total_score is None
        ):
            break

        subgroup_ids.append(best_candidate)
        subgroup_ids.sort()
        logical_score = best_logical_score
        physical_penalty = best_physical_penalty
        total_score = best_total_score

    return subgroup_ids, logical_score, total_score


def _top_candidates_by_affinity(
    candidates: list[str],
    subgroup_ids: list[str],
    affinity_graph: AffinityGraph,
    cap: int,
) -> list[str]:
    scored: list[tuple[float, str]] = []
    for candidate in candidates:
        scored.append((_affinity_delta(candidate, subgroup_ids, affinity_graph), candidate))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[1] for item in scored[:cap]]


def _affinity_delta(
    candidate: str,
    subgroup_ids: list[str],
    affinity_graph: AffinityGraph,
) -> float:
    return sum(
        _lookup_affinity(candidate, sku_id, affinity_graph) for sku_id in subgroup_ids
    )


def _handle_remaining_skus(
    remaining_list: list[str],
    group_id: str,
    subgroups: list[Subgroup],
    sku_by_id: dict[str, SKU],
    affinity_graph: AffinityGraph,
    config: MicroSlottingConfig,
    next_index: int,
    max_size: int,
    units_by_sku: dict[str, float],
    physical_penalty_cache: dict[tuple[str, ...], float],
) -> None:
    allow_singleton = (
        config.subgroup_allow_singleton
        or config.subgroup_singleton_strategy == "allow_singleton"
    )

    if not subgroups or (allow_singleton and len(remaining_list) >= 2):
        _append_singletons(subgroups, group_id, remaining_list, next_index)
        return

    for sku_id in remaining_list:
        best_idx = _select_best_existing_subgroup(
            sku_id=sku_id,
            subgroups=subgroups,
            sku_by_id=sku_by_id,
            affinity_graph=affinity_graph,
            config=config,
            max_size=max_size,
            units_by_sku=units_by_sku,
            physical_penalty_cache=physical_penalty_cache,
        )

        if best_idx is None:
            _append_subgroup(
                subgroups=subgroups,
                subgroup_id=f"{group_id}-h{next_index}",
                group_id=group_id,
                sku_ids=[sku_id],
                score=0.0,
            )
            next_index += 1
            continue

        subgroup = subgroups[best_idx]
        subgroup.sku_ids.append(sku_id)
        subgroup.sku_ids.sort()
        subgroups[best_idx] = Subgroup(
            subgroup_id=subgroup.subgroup_id,
            group_id=subgroup.group_id,
            sku_ids=subgroup.sku_ids,
            score=logical_group_kpi(
                subgroup.sku_ids, sku_by_id, affinity_graph, config, units_by_sku
            ),
        )


def _build_unassigned_subgroups(
    unassigned_ids: list[str],
    sku_by_id: dict[str, SKU],
    affinity_graph: AffinityGraph,
    config: MicroSlottingConfig,
) -> list[Subgroup]:
    """Pack unassigned SKUs by height delta + capacity + affinity."""
    max_size = min(config.subgroup_max_size, config.group_max_size)
    usable_area, max_weight = tray_capacity(
        config.tray_base_area_max, config.tray_op_void, config.tray_weight_max
    )
    remaining = sorted(unassigned_ids, key=lambda s: (-sku_by_id[s].height, s))
    remaining_set = set(remaining)
    subgroups: list[Subgroup] = []
    index = 1
    units_by_sku = _units_by_sku(unassigned_ids, sku_by_id)
    physical_penalty_cache: dict[tuple[str, ...], float] = {}

    while remaining_set:
        subgroup_ids = _grow_unassigned_subgroup(
            remaining_set=remaining_set,
            sku_by_id=sku_by_id,
            affinity_graph=affinity_graph,
            config=config,
            max_size=max_size,
            usable_area=usable_area,
            max_weight=max_weight,
            units_by_sku=units_by_sku,
            physical_penalty_cache=physical_penalty_cache,
        )

        subgroup_ids.sort()
        _append_subgroup(
            subgroups=subgroups,
            subgroup_id=f"unassigned-h{index}",
            group_id="unassigned",
            sku_ids=subgroup_ids,
            score=logical_group_kpi(
                subgroup_ids, sku_by_id, affinity_graph, config, units_by_sku
            ),
        )
        index += 1

    return subgroups


def _units_by_sku(sku_ids: list[str], sku_by_id: dict[str, SKU]) -> dict[str, float]:
    return {sku_id: estimate_cycle_units(sku_by_id[sku_id]) for sku_id in sku_ids}


def _select_best_seed_subgroup(
    remaining_set: set[str],
    sku_by_id: dict[str, SKU],
    affinity_graph: AffinityGraph,
    config: MicroSlottingConfig,
    max_size: int,
    units_by_sku: dict[str, float],
    physical_penalty_cache: dict[tuple[str, ...], float],
) -> tuple[list[str], float] | None:
    seed_pairs = _select_seed_pairs(remaining_set, affinity_graph, config)
    if not seed_pairs:
        return None
    best_subgroup_ids: list[str] | None = None
    best_score: float | None = None
    best_total_score: float | None = None
    for a, b, _affinity in seed_pairs:
        subgroup_ids, score, total_score = _grow_subgroup_from_pair(
            a=a,
            b=b,
            remaining_set=remaining_set,
            sku_by_id=sku_by_id,
            affinity_graph=affinity_graph,
            config=config,
            max_size=max_size,
            units_by_sku=units_by_sku,
            physical_penalty_cache=physical_penalty_cache,
        )
        if best_total_score is None or total_score > best_total_score or (
            total_score == best_total_score and subgroup_ids < (best_subgroup_ids or [])
        ):
            best_subgroup_ids = subgroup_ids
            best_score = score
            best_total_score = total_score
    if not best_subgroup_ids or best_score is None:
        return None
    return best_subgroup_ids, best_score


def _append_subgroup(
    subgroups: list[Subgroup],
    subgroup_id: str,
    group_id: str,
    sku_ids: list[str],
    score: float,
) -> None:
    subgroups.append(
        Subgroup(
            subgroup_id=subgroup_id,
            group_id=group_id,
            sku_ids=sku_ids,
            score=score,
        )
    )


def _append_singletons(
    subgroups: list[Subgroup],
    group_id: str,
    remaining_list: list[str],
    next_index: int,
) -> None:
    for idx, sku_id in enumerate(remaining_list, start=next_index):
        _append_subgroup(
            subgroups=subgroups,
            subgroup_id=f"{group_id}-h{idx}",
            group_id=group_id,
            sku_ids=[sku_id],
            score=0.0,
        )


def _select_best_existing_subgroup(
    sku_id: str,
    subgroups: list[Subgroup],
    sku_by_id: dict[str, SKU],
    affinity_graph: AffinityGraph,
    config: MicroSlottingConfig,
    max_size: int,
    units_by_sku: dict[str, float],
    physical_penalty_cache: dict[tuple[str, ...], float],
) -> int | None:
    best_delta: float | None = None
    best_idx: int | None = None
    for idx, subgroup in enumerate(subgroups):
        if len(subgroup.sku_ids) >= max_size:
            continue
        current_score = logical_group_kpi(
            subgroup.sku_ids, sku_by_id, affinity_graph, config, units_by_sku
        )
        current_physical_penalty = _subgroup_physical_penalty(
            subgroup.sku_ids, sku_by_id, config, physical_penalty_cache
        )
        current_total = current_score - current_physical_penalty
        candidate_ids = sorted(subgroup.sku_ids + [sku_id])
        candidate_score = logical_group_kpi(
            candidate_ids, sku_by_id, affinity_graph, config, units_by_sku
        )
        candidate_physical_penalty = _subgroup_physical_penalty(
            candidate_ids, sku_by_id, config, physical_penalty_cache
        )
        candidate_total = candidate_score - candidate_physical_penalty
        delta = candidate_total - current_total
        if best_delta is None or delta > best_delta or (
            delta == best_delta
            and subgroup.subgroup_id < subgroups[best_idx].subgroup_id  # type: ignore[index]
        ):
            best_delta = delta
            best_idx = idx
    if best_delta is None or best_delta <= config.subgroup_min_delta:
        return None
    return best_idx


def _grow_unassigned_subgroup(
    remaining_set: set[str],
    sku_by_id: dict[str, SKU],
    affinity_graph: AffinityGraph,
    config: MicroSlottingConfig,
    max_size: int,
    usable_area: float,
    max_weight: float,
    units_by_sku: dict[str, float],
    physical_penalty_cache: dict[tuple[str, ...], float],
) -> list[str]:
    start = min(remaining_set, key=lambda s: (-sku_by_id[s].height, s))
    subgroup_ids = [start]
    remaining_set.remove(start)
    min_h = sku_by_id[start].height
    max_h = sku_by_id[start].height
    total_area, total_weight = cycle_area_weight(sku_by_id[start])
    logical_score = logical_group_kpi(
        subgroup_ids, sku_by_id, affinity_graph, config, units_by_sku
    )
    physical_penalty = _subgroup_physical_penalty(
        subgroup_ids, sku_by_id, config, physical_penalty_cache
    )
    total_score = logical_score - physical_penalty

    while len(subgroup_ids) < max_size:
        candidates: list[tuple[float, float, str, float, float]] = []
        for sku_id in remaining_set:
            height = sku_by_id[sku_id].height
            new_min = min(min_h, height)
            new_max = max(max_h, height)
            if (new_max - new_min) > config.unassigned_height_delta_max:
                continue
            area, weight = cycle_area_weight(sku_by_id[sku_id])
            if total_area + area > usable_area or total_weight + weight > max_weight:
                continue
            candidate_ids = sorted(subgroup_ids + [sku_id])
            candidate_logical_score = logical_group_kpi(
                candidate_ids, sku_by_id, affinity_graph, config, units_by_sku
            )
            candidate_physical_penalty = _subgroup_physical_penalty(
                candidate_ids, sku_by_id, config, physical_penalty_cache
            )
            candidate_total_score = (
                candidate_logical_score - candidate_physical_penalty
            )
            delta_total = candidate_total_score - total_score
            candidates.append(
                (
                    delta_total,
                    height,
                    sku_id,
                    candidate_logical_score,
                    candidate_physical_penalty,
                )
            )
        if not candidates:
            break
        candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
        best_delta, height, sku_id, best_logical_score, best_physical_penalty = candidates[0]
        if best_delta <= config.subgroup_min_delta:
            break
        subgroup_ids.append(sku_id)
        remaining_set.remove(sku_id)
        min_h = min(min_h, height)
        max_h = max(max_h, height)
        add_area, add_weight = cycle_area_weight(sku_by_id[sku_id])
        total_area += add_area
        total_weight += add_weight
        logical_score = best_logical_score
        physical_penalty = best_physical_penalty
        total_score = logical_score - physical_penalty

    return subgroup_ids


def _subgroup_physical_penalty(
    sku_ids: list[str],
    sku_by_id: dict[str, SKU],
    config: MicroSlottingConfig,
    physical_penalty_cache: dict[tuple[str, ...], float],
) -> float:
    key = tuple(sorted(sku_ids))
    cached = physical_penalty_cache.get(key)
    if cached is not None:
        return cached
    subgroup = Subgroup(
        subgroup_id="__eval__",
        group_id="__eval__",
        sku_ids=list(key),
        score=0.0,
    )
    try:
        trays = build_trays_for_subgroup(
            subgroup, sku_by_id, config, max_trays_limit=config.max_trays
        )
    except ValueError:
        penalty = float("inf")
        physical_penalty_cache[key] = penalty
        return penalty
    tray_count = len(trays)
    area_used = sum(tray.area_used for tray in trays)
    area_capacity = sum(tray.max_area for tray in trays)
    area_waste_ratio = 0.0
    if area_capacity > 0:
        area_waste_ratio = max(area_capacity - area_used, 0.0) / area_capacity
    penalty = (
        config.subgroup_marginal_tray_weight * float(tray_count)
        + config.subgroup_marginal_area_waste_weight * float(area_waste_ratio)
    )
    physical_penalty_cache[key] = penalty
    return penalty
