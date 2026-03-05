from __future__ import annotations

from slotting.algorithms.micro.group_score import estimate_cycle_units
from slotting.models import SKU


def sku_unit_area_mm2(sku: SKU) -> float:
    height_mm = max(sku.height, 1e-9)
    volume_mm3 = sku.volume * 1e9
    return volume_mm3 / height_mm


def cycle_area_weight(sku: SKU) -> tuple[float, float]:
    units = estimate_cycle_units(sku)
    area = units * sku_unit_area_mm2(sku)
    weight = units * sku.weight
    return area, weight


def tray_capacity(base_area_max: float, op_void: float, weight_max: float) -> tuple[float, float]:
    max_area = base_area_max * (1.0 - op_void)
    if max_area <= 0:
        print("⚠️ [Alerta] Usable tray area debe ser > 0. Usando fallback 1.0 mm².")
        max_area = 1.0
    if weight_max <= 0:
        print("⚠️ [Alerta] Tray weight max debe ser > 0. Usando fallback 1.0 kg.")
        weight_max = 1.0
    return max_area, weight_max
