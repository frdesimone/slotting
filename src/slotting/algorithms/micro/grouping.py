from __future__ import annotations

from collections.abc import Iterable

from slotting.algorithms.micro.config import MicroSlottingConfig
from slotting.algorithms.micro.group_score import group_score
from slotting.models import AffinityGroup, Order, SKU
from .affinity_graph import build_affinity_graph


def build_groups(
    skus: Iterable[SKU],
    orders: Iterable[Order],
    config: MicroSlottingConfig,
) -> list[AffinityGroup]:
    """
    Build one affinity group per seed using a greedy expansion strategy.

    Notes:
    - Seeds are the top SKUs by rotation.
    - Candidate pool is provided by the configured candidate selector.
    - Group affinity scoring is delegated to the configured affinity scorer.
    """
    sku_list = list(skus)
    sku_by_id = {sku.sku_id: sku for sku in sku_list}
    affinity_graph = _build_affinity_graph(orders, config)
    seeds = _select_seeds(sku_list, config)

    groups: list[AffinityGroup] = []
    for seed in seeds:
        groups.append(
            _build_group_for_seed(
                seed=seed,
                sku_by_id=sku_by_id,
                affinity_graph=affinity_graph,
                config=config,
            )
        )

    return groups


def _group_score(
    seed_id: str,
    group_ids: list[str],
    sku_by_id: dict[str, SKU],
    affinity_graph: dict[str, list],
    config: MicroSlottingConfig,
) -> float:
    return group_score(
        seed_id=seed_id,
        group_ids=group_ids,
        sku_by_id=sku_by_id,
        affinity_graph=affinity_graph,
        config=config,
    )


def _build_affinity_graph(
    orders: Iterable[Order],
    config: MicroSlottingConfig,
) -> dict[str, list]:
    return build_affinity_graph(
        orders=orders,
        top_k=config.top_k_neighbors,
        aff_min=config.aff_min,
        metric=config.affinity_metric,
    )


def _select_seeds(sku_list: list[SKU], config: MicroSlottingConfig) -> list[SKU]:
    sorted_skus = sorted(sku_list, key=lambda s: s.rot, reverse=True)
    seed_count = min(config.seed_count, len(sorted_skus))
    if seed_count <= 0:
        return []

    def take_evenly(items: list[SKU], count: int) -> list[SKU]:
        if count <= 0 or not items:
            return []
        if count >= len(items):
            return list(items)
        chosen: list[SKU] = []
        used_idx: set[int] = set()
        for i in range(count):
            idx = int((i + 0.5) * len(items) / count)
            if idx >= len(items):
                idx = len(items) - 1
            j = idx
            while j < len(items) and j in used_idx:
                j += 1
            if j >= len(items):
                j = idx
                while j >= 0 and j in used_idx:
                    j -= 1
            if j < 0:
                break
            used_idx.add(j)
            chosen.append(items[j])
        return chosen

    n = len(sorted_skus)
    p40 = int(n * 0.40)
    p80 = int(n * 0.80)

    top = sorted_skus[:p40] if p40 > 0 else []
    mid = sorted_skus[p40:p80] if p80 > p40 else []
    tail = sorted_skus[p80:] if p80 < n else []

    top_count = int(round(seed_count * 0.4))
    mid_count = int(round(seed_count * 0.4))
    tail_count = seed_count - top_count - mid_count

    selected: list[SKU] = []
    selected.extend(take_evenly(top, top_count))
    selected.extend(take_evenly(mid, mid_count))
    selected.extend(take_evenly(tail, tail_count))

    if len(selected) < seed_count:
        selected_ids = {sku.sku_id for sku in selected}
        for sku in sorted_skus:
            if sku.sku_id in selected_ids:
                continue
            selected.append(sku)
            if len(selected) >= seed_count:
                break

    return selected


def _build_group_for_seed(
    seed: SKU,
    sku_by_id: dict[str, SKU],
    affinity_graph: dict[str, list],
    config: MicroSlottingConfig,
) -> AffinityGroup:
    group_ids = [seed.sku_id]
    score = _group_score(
        seed_id=seed.sku_id,
        group_ids=group_ids,
        sku_by_id=sku_by_id,
        affinity_graph=affinity_graph,
        config=config,
    )
    candidate_ids = config.candidate_selector.select(
        seed_id=seed.sku_id,
        affinity_graph=affinity_graph,
    )

    while True:
        if len(group_ids) >= config.max_group_size:
            break

        best_delta = None
        best_candidate = None
        for candidate_id in candidate_ids:
            if candidate_id in group_ids:
                continue
            new_group_ids = group_ids + [candidate_id]
            new_score = _group_score(
                seed_id=seed.sku_id,
                group_ids=new_group_ids,
                sku_by_id=sku_by_id,
                affinity_graph=affinity_graph,
                config=config,
            )
            delta = new_score - score
            if best_delta is None or delta > best_delta:
                best_delta = delta
                best_candidate = (candidate_id, new_score)

        if best_delta is None or best_delta < config.min_delta:
            break

        group_ids.append(best_candidate[0])
        score = best_candidate[1]

    return AffinityGroup(seed_sku_id=seed.sku_id, sku_ids=group_ids, score=score)
