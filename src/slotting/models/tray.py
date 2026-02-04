from __future__ import annotations

from dataclasses import dataclass

from slotting.models.group import Subgroup


@dataclass
class TrayItem:
    sku_id: str
    units: float
    unit_volume: float
    unit_weight: float
    total_volume: float
    total_weight: float
    unit_area: float
    total_area: float


@dataclass
class Tray:
    tray_id: str
    group_id: str
    subgroup_id: str
    height: float
    max_area: float
    max_weight: float
    area_used: float
    weight_used: float
    items: list[TrayItem]


@dataclass
class TrayPlan:
    group_id: str
    subgroups: list[Subgroup]
    trays: list[Tray]
