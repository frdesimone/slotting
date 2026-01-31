from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TrayItem:
    sku_id: str
    units: float
    unit_volume: float
    unit_weight: float
    total_volume: float
    total_weight: float


@dataclass
class Tray:
    tray_id: str
    group_id: str
    height: float
    max_volume: float
    max_weight: float
    items: list[TrayItem]
