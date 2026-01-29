from __future__ import annotations
from pathlib import Path

from slotting.models import Order, SKU
from .codes import SkuRecord, load_sku_records_from_codes
from .orders import load_orders_from_pedidos
from .stats import PrepStats

def load_slotting_inputs(
    codes_csv_path: str | Path,
    orders_csv_path: str | Path,
    cycle_days: float,
    period_days: float = 180.0,
    include_zero_rot: bool = False,
) -> tuple[list[SKU], list[Order], PrepStats]:
    """
    Carga genérica de datos para Micro y Macro slotting.
    """
    _validate_input_params(cycle_days=cycle_days, period_days=period_days)
    stats = PrepStats()
    
    # 1. Cargar Maestro de Materiales (con flags de Macro)
    sku_records = load_sku_records_from_codes(codes_csv_path)
    stats.total_skus_master = len(sku_records)
    
    # 2. Cargar Pedidos (Historia)
    allowed_skus = set(sku_records.keys())
    orders, rot_by_sku, units_by_sku, order_stats = load_orders_from_pedidos(
        orders_csv_path,
        allowed_skus=allowed_skus,
    )
    stats.order_stats = order_stats

    # 3. Fusionar info en objetos SKU finales
    skus = _build_skus(
        sku_records=sku_records,
        rot_by_sku=rot_by_sku,
        units_by_sku=units_by_sku,
        cycle_days=cycle_days,
        period_days=period_days,
        include_zero_rot=include_zero_rot,
        stats=stats,
    )
    
    # 4. Filtrar órdenes para que solo tengan SKUs válidos
    filtered_orders = _filter_orders_by_skus(orders, skus, stats)

    return skus, filtered_orders, stats

def _build_skus(
    sku_records: dict[str, SkuRecord],
    rot_by_sku: dict[str, int],
    units_by_sku: dict[str, float],
    cycle_days: float,
    period_days: float,
    include_zero_rot: bool,
    stats: PrepStats,
) -> list[SKU]:
    skus: list[SKU] = []
    for sku_id, record in sku_records.items():
        rot = rot_by_sku.get(sku_id, 0)
        
        # Filtro opcional de rotación 0 (útil para no procesar basura)
        if rot <= 0 and not include_zero_rot:
            stats.skipped_zero_rot += 1
            continue
            
        # Validación de datos físicos mínimos
        if record.height is None or record.volume is None or record.weight is None:
            stats.skipped_missing_data += 1
            continue
        
        # Datos de venta
        total_units_sold = units_by_sku.get(sku_id, 0.0)
        cycle_units = total_units_sold * (cycle_days / period_days)

        skus.append(
            SKU(
                sku_id=sku_id,
                rot=float(rot),
                height=record.height,
                volume=record.volume,
                weight=record.weight,
                cycle_units=cycle_units,
                avg_units_per_line=record.avg_units_per_line,
                # --- Campos nuevos populados ---
                units_sold_total=total_units_sold,
                is_sensitive=record.is_sensitive,
                vlm_eligible=record.vlm_eligible,
                # -------------------------------
            )
        )
    stats.total_skus_final = len(skus)
    return skus

def _filter_orders_by_skus(orders: list[Order], skus: list[SKU], stats: PrepStats) -> list[Order]:
    valid_skus = {sku.sku_id for sku in skus}
    filtered_orders: list[Order] = []
    for order in orders:
        sku_ids = [s for s in order.sku_ids if s in valid_skus]
        if not sku_ids:
            stats.orders_filtered_empty += 1
            continue
        filtered_orders.append(Order(order_id=order.order_id, sku_ids=sku_ids))
    return filtered_orders

def _validate_input_params(cycle_days: float, period_days: float) -> None:
    if cycle_days <= 0: raise ValueError("cycle_days must be > 0")
    if period_days <= 0: raise ValueError("period_days must be > 0")