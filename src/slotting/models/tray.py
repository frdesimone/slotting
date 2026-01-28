from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tray:
    tray_id: str
    height: float
    max_volume: float
    max_weight: float
