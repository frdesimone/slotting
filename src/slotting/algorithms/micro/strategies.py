from __future__ import annotations

from abc import ABC, abstractmethod

from slotting.models import AffinityNeighbor
from typing import TypeAlias

AffinityGraph: TypeAlias = dict[str, list[AffinityNeighbor]]


class AffinityMetric(ABC):
    """Compute pairwise affinity from co-occurrence counts."""
    @abstractmethod
    def compute(self, with_a: int, with_b: int, both: int) -> float | None:
        raise NotImplementedError


class JaccardMetric(AffinityMetric):
    """Jaccard similarity: both / (with_a + with_b - both)."""
    def compute(self, with_a: int, with_b: int, both: int) -> float | None:
        denom = with_a + with_b - both
        if denom <= 0:
            return None
        return both / denom


class LiftMetric(AffinityMetric):
    """Lift-style metric: both / sqrt(with_a * with_b)."""
    def compute(self, with_a: int, with_b: int, both: int) -> float | None:
        if with_a <= 0 or with_b <= 0:
            return None
        return both / ((with_a * with_b) ** 0.5)


class AffinityScorer(ABC):
    """Compute total affinity for a candidate group."""
    @abstractmethod
    def score(
        self,
        seed_id: str,
        group_ids: list[str],
        affinity_graph: AffinityGraph,
    ) -> float:
        raise NotImplementedError


class StarAffinityScorer(AffinityScorer):
    """Sum affinities between the seed and each member (star model)."""
    def score(
        self,
        seed_id: str,
        group_ids: list[str],
        affinity_graph: AffinityGraph,
    ) -> float:
        neighbors = {n.sku_id: n.affinity for n in affinity_graph.get(seed_id, [])}
        benefit = 0.0
        for sku_id in group_ids:
            if sku_id == seed_id:
                continue
            benefit += neighbors.get(sku_id, 0.0)
        return benefit


class FullAffinityScorer(AffinityScorer):
    """Sum affinities over all pairwise combinations in the group."""
    def score(
        self,
        seed_id: str,
        group_ids: list[str],
        affinity_graph: AffinityGraph,
    ) -> float:
        benefit = 0.0
        for idx, sku_id in enumerate(group_ids):
            for other_id in group_ids[idx + 1 :]:
                benefit += _lookup_affinity(sku_id, other_id, affinity_graph)
        return benefit


class CandidateSelector(ABC):
    """Select candidate SKU ids to expand a group."""
    @abstractmethod
    def select(
        self,
        seed_id: str,
        affinity_graph: AffinityGraph,
    ) -> list[str]:
        raise NotImplementedError


class OneHopCandidateSelector(CandidateSelector):
    """Candidates are direct neighbors of the seed."""
    def select(
        self,
        seed_id: str,
        affinity_graph: AffinityGraph,
    ) -> list[str]:
        return [n.sku_id for n in affinity_graph.get(seed_id, [])]


class TwoHopCandidateSelector(CandidateSelector):
    """Candidates are 1-hop plus neighbors of neighbors."""
    def select(
        self,
        seed_id: str,
        affinity_graph: AffinityGraph,
    ) -> list[str]:
        one_hop = {n.sku_id for n in affinity_graph.get(seed_id, [])}
        all_candidates = set(one_hop)
        for neighbor_id in one_hop:
            all_candidates.update(
                n.sku_id for n in affinity_graph.get(neighbor_id, [])
            )
        all_candidates.discard(seed_id)
        return sorted(all_candidates)


def _lookup_affinity(
    sku_id: str,
    other_id: str,
    affinity_graph: AffinityGraph,
) -> float:
    for neighbor in affinity_graph.get(sku_id, []):
        if neighbor.sku_id == other_id:
            return neighbor.affinity
    for neighbor in affinity_graph.get(other_id, []):
        if neighbor.sku_id == sku_id:
            return neighbor.affinity
    return 0.0
