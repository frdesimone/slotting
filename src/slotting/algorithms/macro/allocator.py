from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from slotting.models import SKU
from .config import MacroSlottingConfig

StorageType = Literal["VLM", "JAULA", "RACK"]

@dataclass
class MacroResult:
    sku_id: str
    storage_type: str
    abc_class: str
    cycle_volume: float
    reason: str
    description: str = ""
    boxes_per_m3: float = 0.0
    category: str = ""

def run_macro_slotting(
    skus: list[SKU],
    config: MacroSlottingConfig
) -> list[MacroResult]:
    
    # 1. ABC (igual que antes)
    skus_by_rot = sorted(skus, key=lambda s: s.rot, reverse=True)
    total_system_rot = sum(s.rot for s in skus)
    sku_abc_map = {}
    accumulated_rot = 0.0
    limit_a, limit_b = config.abc_thresholds
    
    for sku in skus_by_rot:
        accumulated_rot += sku.rot
        pct = accumulated_rot / total_system_rot if total_system_rot > 0 else 1.0
        sku_abc_map[sku.sku_id] = "A" if pct <= limit_a else ("B" if pct <= limit_b else "C")

    # 2. Cola de prioridad
    buckets = {"A": [], "B": [], "C": []}
    for sku in skus: buckets[sku_abc_map[sku.sku_id]].append(sku)
    for key in buckets: buckets[key].sort(key=lambda s: s.rot, reverse=True)
    priority_queue = buckets["A"] + buckets["B"] + buckets["C"]

    # 3. Preparar los Storage Types (Ordenados por prioridad 1, 2, 3...)
    sorted_storages = sorted(config.storage_types, key=lambda x: int(x.get("priority", 99)))
    
    usage = {st["name"]: 0.0 for st in sorted_storages}
    limits = {st["name"]: float(st.get("capacity", float('inf'))) * float(st.get("occupancy", 1.0)) for st in sorted_storages}
    
    results: list[MacroResult] = []
    debug_math_logged = False

    # 4. Asignación Dinámica
    for sku in priority_queue:
        abc = sku_abc_map[sku.sku_id]
        sku_rot = getattr(sku, 'rot', 0.0) or 0.0
        sku_vol = getattr(sku, 'volume', 0.0) or 0.0
        sku_desc = getattr(sku, 'description', '') or ''
        sku_boxes = getattr(sku, 'boxes_per_m3', 0.0) or 0.0
        sku_cat = getattr(sku, 'category', '') or ''
        
        # 1. Obtenemos el histórico de días real calculado por el loader
        period_days = getattr(sku, 'period_days', 180.0) or 180.0
        # 2. Unidades físicas vendidas por día
        total_units = getattr(sku, 'units_sold_total', 0.0) or 0.0
        units_per_day = total_units / period_days if period_days > 0 else 0.0
        
        assigned = False
        
        for st in sorted_storages:
            name = st["name"]
            cycle_days = float(st.get("cycle_days", 15.0))
            max_vol = float(st.get("max_volume", float('inf')))
            max_weight = float(st.get("max_weight", float('inf')))
            max_cycle_vol_limit = float(st.get("max_cycle_volume_limit", float('inf')))
            allowed_cats = st.get("allowed_categories") or []
            if isinstance(allowed_cats, str):
                allowed_cats = [c.strip() for c in allowed_cats.split(",") if c.strip()]
            elif not isinstance(allowed_cats, list):
                allowed_cats = []

            # 3. Volumen de Ciclo = (Unidades diarias * Días de cobertura de la estantería) * Volumen unitario
            cycle_vol = (units_per_day * cycle_days) * sku_vol

            if not debug_math_logged:
                print(f"\n🔍 [DEBUG MATH MACRO] SKU: {sku.sku_id}")
                print(f"   -> total_units_sold: {total_units}")
                print(f"   -> period_days: {period_days}")
                print(f"   -> units_per_day (total/period): {units_per_day}")
                print(f"   -> sku_vol (volumen unitario): {sku_vol}")
                print(f"   -> cycle_days (cobertura): {cycle_days}")
                print(f"   -> cycle_vol FINAL: {cycle_vol}\n")
                debug_math_logged = True

            # Reglas de rechazo: límite de volumen de ciclo
            if cycle_vol > max_cycle_vol_limit:
                continue
            
            # Reglas de rechazo: categorías permitidas (vacío = permitir todas; solo rechazar si hay filtro Y el SKU no cumple)
            if allowed_cats and sku_cat.strip().lower() not in [c.strip().lower() for c in allowed_cats]:
                continue
            
            # Reglas físicas: volumen y peso por SKU
            if sku_vol > max_vol or sku.weight > max_weight:
                continue
                
            # Verificamos si queda espacio en esta ubicación
            if usage[name] + cycle_vol <= limits[name]:
                usage[name] += cycle_vol
                results.append(MacroResult(
                    sku_id=sku.sku_id,
                    storage_type=name,
                    abc_class=abc,
                    cycle_volume=cycle_vol,
                    reason=f"Fits constraints of {name}",
                    description=sku_desc,
                    boxes_per_m3=sku_boxes,
                    category=sku_cat
                ))
                assigned = True
                break
                
        if not assigned:
            cycle_days_default = float(sorted_storages[0].get("cycle_days", 15.0)) if sorted_storages else 15.0
            cycle_vol = (units_per_day * cycle_days_default) * sku_vol

            if not debug_math_logged:
                print(f"\n🔍 [DEBUG MATH MACRO] SKU: {sku.sku_id}")
                print(f"   -> total_units_sold: {total_units}")
                print(f"   -> period_days: {period_days}")
                print(f"   -> units_per_day (total/period): {units_per_day}")
                print(f"   -> sku_vol (volumen unitario): {sku_vol}")
                print(f"   -> cycle_days (cobertura): {cycle_days_default}")
                print(f"   -> cycle_vol FINAL: {cycle_vol}\n")
                debug_math_logged = True

            results.append(MacroResult(
                sku_id=sku.sku_id,
                storage_type="UNASSIGNED",
                abc_class=abc,
                cycle_volume=cycle_vol,
                reason="No storage type matched constraints or capacity",
                description=sku_desc,
                boxes_per_m3=sku_boxes,
                category=sku_cat
            ))
            
    return results