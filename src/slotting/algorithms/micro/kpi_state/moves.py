from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SwapMove:
    sku_a: str
    sku_b: str


@dataclass(frozen=True)
class RelocateMove:
    sku_id: str
    from_subgroup_id: str
    to_subgroup_id: str


Move = SwapMove | RelocateMove
