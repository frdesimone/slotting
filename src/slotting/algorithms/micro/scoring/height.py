from __future__ import annotations

from slotting.models import SKU, Tray


def _avg_height_by_area(total_volume_mm3: float, total_area_mm2: float) -> float:
    if total_area_mm2 <= 0:
        return 0.0
    return total_volume_mm3 / total_area_mm2


def height_diff_by_area_for_skus(
    sku_ids: list[str],
    sku_by_id: dict[str, SKU],
    units_by_sku: dict[str, float],
) -> float:
    if not sku_ids:
        return 0.0
    max_height = max(sku_by_id[sku_id].height for sku_id in sku_ids)
    total_volume_mm3 = 0.0
    total_area_mm2 = 0.0
    for sku_id in sku_ids:
        sku = sku_by_id[sku_id]
        units = units_by_sku.get(sku_id, 0.0)
        if units <= 0:
            continue
        volume_mm3 = units * sku.volume * 1e9
        total_volume_mm3 += volume_mm3
        total_area_mm2 += volume_mm3 / max(sku.height, 1e-9)
    avg_height = _avg_height_by_area(total_volume_mm3, total_area_mm2)
    return max_height - avg_height


def height_diff_by_area_for_tray(tray: Tray) -> float:
    total_volume_mm3 = sum(item.total_volume for item in tray.items) * 1e9
    total_area_mm2 = sum(item.total_area for item in tray.items)
    avg_height = _avg_height_by_area(total_volume_mm3, total_area_mm2)
    return tray.height - avg_height


def convex_height_penalty(diff: float, ref: float, p: float) -> float:
    if diff <= 0:
        return 0.0
    denom = max(ref, 1e-9)
    exponent = max(p, 1e-9)
    return (diff / denom) ** exponent
