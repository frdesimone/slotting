from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SKU:
    sku_id: str
    rot: float
    height: float
    volume: float
    weight: float
    cycle_units: float | None = None
    avg_units_per_line: float | None = None
