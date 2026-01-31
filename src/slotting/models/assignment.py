from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GroupAllocation:
    group_id: str
    vlm_ids: list[str]
    replication_split: list[float]


@dataclass
class TrayAssignment:
    tray_id: str
    vlm_id: str
    group_id: str
