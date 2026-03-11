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
    total_weight: float = 0.0
    total_vol: float = 0.0
    sku_vol: float = 0.0
    actual_sales_units: float = 0.0
    replenishment_units: float = 0.0
    width: float = 0.0
    length: float = 0.0
    height: float = 0.0

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
    sorted_storages = sorted(config.storage_types, key=lambda x: x.priority)

    usage = {st.name: 0.0 for st in sorted_storages}
    storage_capacity_info = {}
    for st in sorted_storages:
        total_cap, max_loc = st._capacity_and_max_loc_vol()
        storage_capacity_info[st.name] = {"total_capacity_m3": total_cap, "max_loc_vol": max_loc}
    limits = {st.name: storage_capacity_info[st.name]["total_capacity_m3"] for st in sorted_storages}
    
    results: list[MacroResult] = []
    debug_math_logged = False

    # 4. Asignación Dinámica
    for sku in priority_queue:
        abc = sku_abc_map[sku.sku_id]
        sku_vol = getattr(sku, "volume", 0.0) or 0.0
        sku_desc = getattr(sku, "description", "") or ""
        sku_cat = getattr(sku, "category", "") or ""
        sku_w = float(getattr(sku, "width", 0) or 0) / 100.0
        sku_l = float(getattr(sku, "length", 0) or 0) / 100.0
        sku_h = float(getattr(sku, "height", 0) or 0) / 100.0
        if sku_vol <= 0 and (sku_w > 0 and sku_l > 0 and sku_h > 0):
            sku_vol = sku_w * sku_l * sku_h

        period_days = getattr(sku, "period_days", 180.0) or 180.0
        total_units = getattr(sku, "units_sold_total", 0.0) or 0.0
        units_per_day = total_units / period_days if period_days > 0 else 0.0

        assigned = False

        for st in sorted_storages:
            name = st.name
            cycle_days = float(st.cycle_days)
            max_cycle_vol_limit = st.cycle_vol_limit
            allowed_cats = st.categories
            max_w_loc = getattr(st, "max_w", float("inf"))
            max_l_loc = getattr(st, "max_l", float("inf"))
            cap_info = storage_capacity_info.get(name, {})
            max_loc_vol = cap_info.get("max_loc_vol", float("inf"))

            cycle_vol = (units_per_day * cycle_days) * sku_vol
            cycle_qty = units_per_day * cycle_days

            if not debug_math_logged:
                print(f"\n[DEBUG MATH MACRO] SKU: {sku.sku_id} -> cycle_vol: {cycle_vol}, cycle_qty: {cycle_qty}\n")
                debug_math_logged = True

            if cycle_vol > max_cycle_vol_limit:
                continue

            if allowed_cats and sku_cat.strip().lower() not in [c.strip().lower() for c in allowed_cats]:
                continue

            # Descarte por peso
            if sku.weight and float(sku.weight) > st.max_weight_loc:
                continue

            # Descarte por volumen: SKU no puede ser más voluminoso que la ubicación máxima
            if sku_vol > max_loc_vol:
                continue

            # Descarte por superficie/dimensiones (verificando que el SKU entre físicamente, permitiendo rotarlo 90 grados)
            sku_min_dim = min(sku_w, sku_l)
            sku_max_dim = max(sku_w, sku_l)
            loc_min_dim = min(max_w_loc, max_l_loc)
            loc_max_dim = max(max_w_loc, max_l_loc)
            if sku_min_dim > loc_min_dim or sku_max_dim > loc_max_dim:
                continue

            if usage[name] + cycle_vol <= limits[name]:
                usage[name] += cycle_vol

                # --- CÁLCULO DE REPOSICIÓN Y LOGGING ---
                um_ratio = 1.0
                for attr in ["um_ratio", "boxes_per_m3", "cajas_m3"]:
                    val = getattr(sku, attr, None)
                    if val is not None:
                        try:
                            if float(val) > 0:
                                um_ratio = float(val)
                                break
                        except (ValueError, TypeError):
                            pass

                unidades_venta = (cycle_vol / sku_vol) if sku_vol > 0 else cycle_qty
                rep_units = unidades_venta / um_ratio

                print(f"📦 [MACRO MATH] SKU: {sku.sku_id} | Vol.Ciclo: {cycle_vol:.4f} / Vol.Unitario: {sku_vol:.6f} = {unidades_venta:.2f} Unidades Venta | Ratio: {um_ratio} -> REPOSICIÓN: {rep_units:.2f}")

                total_sku_weight = unidades_venta * float(sku.weight or 0)

                results.append(
                    MacroResult(
                        sku_id=sku.sku_id,
                        storage_type=name,
                        abc_class=abc,
                        cycle_volume=cycle_vol,
                        reason=f"Fits constraints of {name}",
                        description=sku_desc,
                        boxes_per_m3=um_ratio,
                        category=sku_cat,
                        total_weight=total_sku_weight,
                        total_vol=cycle_vol,
                        sku_vol=sku_vol,
                        actual_sales_units=unidades_venta,
                        replenishment_units=rep_units,
                        width=getattr(sku, "width", 0) or 0,
                        length=getattr(sku, "length", 0) or 0,
                        height=getattr(sku, "height", 0) or 0,
                    )
                )
                assigned = True
                break
                
        if not assigned:
            cycle_days_default = float(sorted_storages[0].cycle_days) if sorted_storages else 15.0
            cycle_qty = units_per_day * cycle_days_default
            cycle_vol = cycle_qty * sku_vol

            # --- CÁLCULO DE REPOSICIÓN Y LOGGING ---
            um_ratio = 1.0
            for attr in ["um_ratio", "boxes_per_m3", "cajas_m3"]:
                val = getattr(sku, attr, None)
                if val is not None:
                    try:
                        if float(val) > 0:
                            um_ratio = float(val)
                            break
                    except (ValueError, TypeError):
                        pass

            unidades_venta = (cycle_vol / sku_vol) if sku_vol > 0 else cycle_qty
            rep_units = unidades_venta / um_ratio

            print(f"📦 [MACRO MATH UNASSIGNED] SKU: {sku.sku_id} | Vol.Ciclo: {cycle_vol:.4f} / Vol.Unitario: {sku_vol:.6f} = {unidades_venta:.2f} Unidades Venta | Ratio: {um_ratio} -> REPOSICIÓN: {rep_units:.2f}")

            total_sku_weight = unidades_venta * float(sku.weight or 0)

            results.append(
                MacroResult(
                    sku_id=sku.sku_id,
                    storage_type="UNASSIGNED",
                    abc_class=abc,
                    cycle_volume=cycle_vol,
                    reason="No storage type matched constraints or capacity",
                    description=sku_desc,
                    boxes_per_m3=um_ratio,
                    category=sku_cat,
                    total_weight=total_sku_weight,
                    total_vol=cycle_vol,
                    sku_vol=sku_vol,
                    actual_sales_units=unidades_venta,
                    replenishment_units=rep_units,
                    width=getattr(sku, "width", 0) or 0,
                    length=getattr(sku, "length", 0) or 0,
                    height=getattr(sku, "height", 0) or 0,
                )
            )
            
    return results