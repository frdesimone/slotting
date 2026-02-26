from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from slotting.models import SKU
from .config import MacroSlottingConfig

StorageType = Literal["VLM", "JAULA", "RACK"]

@dataclass
class MacroResult:
    sku_id: str
    storage_type: StorageType
    abc_class: str
    cycle_volume: float
    reason: str

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

    # 4. Asignación Dinámica
    for sku in priority_queue:
        abc = sku_abc_map[sku.sku_id]
        cycle_vol = (sku.cycle_units or 0.0) * sku.volume
        
        assigned = False
        
        for st in sorted_storages:
            name = st["name"]
            max_vol = float(st.get("max_volume", float('inf')))
            max_weight = float(st.get("max_weight", float('inf')))
            
            # Verificamos si el SKU rompe las reglas físicas de esta ubicación
            if sku.volume > max_vol or sku.weight > max_weight:
                continue
                
            # Verificamos si queda espacio en esta ubicación
            if usage[name] + cycle_vol <= limits[name]:
                usage[name] += cycle_vol
                results.append(MacroResult(
                    sku_id=sku.sku_id,
                    storage_type=name,
                    abc_class=abc,
                    cycle_volume=cycle_vol,
                    reason=f"Fits constraints of {name}"
                ))
                assigned = True
                break
                
        if not assigned:
            results.append(MacroResult(
                sku_id=sku.sku_id,
                storage_type="UNASSIGNED",
                abc_class=abc,
                cycle_volume=cycle_vol,
                reason="No storage type matched constraints or capacity"
            ))
            
    return results