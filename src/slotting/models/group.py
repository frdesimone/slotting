from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AffinityNeighbor:
    sku_id: str
    affinity: float


@dataclass
class AffinityGroup:
    seed_sku_id: str
    sku_ids: list[str]
    score: float


@dataclass
class Subgroup:
    subgroup_id: str
    group_id: str
    sku_ids: list[str]
    score: float
