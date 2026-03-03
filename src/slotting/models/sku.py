from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class SKU:
    sku_id: str
    rot: float     
    height: float
    volume: float
    weight: float
    width: float = 0.0             # <--- ACÁ ABAJO
    length: float = 0.0            # <--- ACÁ ABAJO
    units_sold_total: float = 0.0  
    is_sensitive: bool = False     
    vlm_eligible: bool = True     
    description: str = ""
    boxes_per_m3: float = 0.0
    category: str = ""

    cycle_units: float | None = None
    avg_units_per_line: float | None = None