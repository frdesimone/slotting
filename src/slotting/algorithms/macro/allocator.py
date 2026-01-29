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
    
    # --- Paso 1: Clasificación ABC (Basada en ROTACIÓN / LÍNEAS) ---
    # Corrección: Usamos 'rot' (frecuencia de pedidos) en lugar de unidades vendidas.
    # El objetivo es priorizar en VLM los artículos que generan más movimientos (líneas).
    
    # Ordenamos por rotación descendente (líneas/día o líneas totales según periodo)
    skus_by_rot = sorted(skus, key=lambda s: s.rot, reverse=True)
    
    # Calculamos el total de líneas (esfuerzo total de picking)
    total_system_rot = sum(s.rot for s in skus)
    
    sku_abc_map = {}
    accumulated_rot = 0.0
    limit_a, limit_b = config.abc_thresholds
    
    for sku in skus_by_rot:
        accumulated_rot += sku.rot
        # Evitamos división por cero si no hay rotación en todo el sistema
        pct = accumulated_rot / total_system_rot if total_system_rot > 0 else 1.0
        
        if pct <= limit_a:
            abc = "A"
        elif pct <= limit_b:
            abc = "B"
        else:
            abc = "C"
        sku_abc_map[sku.sku_id] = abc

    # --- Paso 2: Preparación de Buckets para Asignación ---
    # Aunque ya están ordenados por rotación, los agrupamos explícitamente por ABC
    # para respetar la jerarquía estricta: Primero llenamos con A, luego B, luego C.
    
    buckets = {"A": [], "B": [], "C": []}
    for sku in skus:
        abc = sku_abc_map[sku.sku_id]
        buckets[abc].append(sku)
        
    # Dentro de cada clase A/B/C, nos aseguramos que estén ordenados por el más rotante al menos rotante.
    for key in buckets:
        buckets[key].sort(key=lambda s: s.rot, reverse=True)
        
    # Cola de prioridad final: Todos los A (ordenados), seguidos de los B, etc.
    priority_queue = buckets["A"] + buckets["B"] + buckets["C"]

    # --- Paso 3 y 4: Asignación con Hard Blocks y Capacidad Volumétrica ---
    
    vlm_capacity_limit = config.vlm_total_usable_volume * config.vlm_occupancy_target
    current_vlm_usage = 0.0
    
    results: list[MacroResult] = []

    for sku in priority_queue:
        abc = sku_abc_map[sku.sku_id]
        
        # El volumen físico que ocupa el stock sigue dependiendo de las UNIDADES (cycle_units),
        # no de la rotación. Un producto A puede ocupar mucho espacio si tiene stock alto.
        cycle_vol = (sku.cycle_units or 0.0) * sku.volume
        
        # Regla 1: Hard Block - Sensibles (A JAULA)
        if sku.is_sensitive:
            results.append(MacroResult(
                sku_id=sku.sku_id,
                storage_type="JAULA",
                abc_class=abc,
                cycle_volume=cycle_vol,
                reason="Hard Block: Sensitive"
            ))
            continue
            
        # Regla 2: Hard Block - No apto VLM (A RACK)
        if not sku.vlm_eligible:
            results.append(MacroResult(
                sku_id=sku.sku_id,
                storage_type="RACK",
                abc_class=abc,
                cycle_volume=cycle_vol,
                reason="Hard Block: Not VLM Eligible"
            ))
            continue
            
        # Regla 3: Capacidad VLM (Greedy)
        # Intentamos meterlo en VLM si entra el volumen de su stock
        if current_vlm_usage + cycle_vol <= vlm_capacity_limit:
            current_vlm_usage += cycle_vol
            results.append(MacroResult(
                sku_id=sku.sku_id,
                storage_type="VLM",
                abc_class=abc,
                cycle_volume=cycle_vol,
                reason="Capacity Fit"
            ))
        else:
            # Si se llenó el VLM, el resto va a RACK (Overflow)
            results.append(MacroResult(
                sku_id=sku.sku_id,
                storage_type="RACK",
                abc_class=abc,
                cycle_volume=cycle_vol,
                reason="VLM Capacity Overflow"
            ))
            
    return results