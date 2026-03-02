import gc
import pandas as pd
from pathlib import Path

from slotting.models import SKU, Order
from .stats import PrepStats
from .codes import load_sku_records_from_codes, SkuRecord
from .orders import load_orders_from_pedidos

def load_slotting_inputs_with_stats(
    file_path: str | Path,
    cycle_days: float,
    period_days: float = 180.0,
    include_zero_rot: bool = False,
    mapping: dict = None,
    excluded_skus: set[str] = None, 
    excluded_orders: set[str] = None, 
) -> tuple[list[SKU], list[Order], PrepStats]:
    """Carga genérica de datos leyendo desde un solo archivo Excel y controlando memoria."""
    if mapping is None:
        mapping = {}

    if excluded_skus is None: excluded_skus = set()
    if excluded_orders is None: excluded_orders = set()

    _validate_input_params(cycle_days=cycle_days, period_days=period_days)
    stats = PrepStats()
    
    # 1. ABRIR EL ARCHIVO UNA SOLA VEZ
    xls = None
    if str(file_path).lower().endswith(('.xlsx', '.xls')):
        print("📦 [Memoria] Abriendo Excel de forma global para evitar duplicados en RAM...")
        xls = pd.ExcelFile(file_path)

    # 2. Cargar Maestro
    sku_records = load_sku_records_from_codes(file_path, mapping=mapping, xls=xls) 
    stats.total_skus_master = len(sku_records)

    print(f"🔍 [Loader] Maestro cargado con {len(sku_records)} SKUs.")
    if sku_records:
        sample_key = next(iter(sku_records.keys()))
        print(f"🔍 [Loader] Ejemplo de ID en Maestro: '{sample_key}' (Tipo: {type(sample_key)})")

    # Calculamos los permitidos restando los excluidos
    allowed_skus = set(sku_records.keys()) - excluded_skus
    print(f"🔍 [Loader] Excluyendo {len(excluded_skus)} SKUs. Quedan {len(allowed_skus)} SKUs permitidos para cargar pedidos.")
    
    # Limpiar RAM intermedia
    gc.collect()
    
    # 3. Cargar Pedidos
    # ELIMINAMOS EL BUG: Ya no sobreescribimos allowed_skus acá
    orders, rot_by_sku, units_by_sku, order_stats = load_orders_from_pedidos(
        file_path, 
        allowed_skus=allowed_skus,
        mapping=mapping,
        xls=xls,
        excluded_orders=excluded_orders 
    )
    stats.order_stats = order_stats

    # 4. CERRAR EL EXCEL Y LIBERAR MEMORIA
    if xls is not None:
        xls.close()
        del xls
        gc.collect()
        print("🧹 [Memoria] Archivo Excel cerrado y RAM liberada.")

    # 5. Fusionar info en objetos SKU finales
    skus = _build_skus(
        sku_records=sku_records,
        rot_by_sku=rot_by_sku,
        units_by_sku=units_by_sku,
        cycle_days=cycle_days,
        period_days=period_days,
        include_zero_rot=include_zero_rot,
        stats=stats,
    )
    
    print(f"🔍 [Loader] _build_skus generó {len(skus)} objetos SKU.")
    if skus:
        print(f"🔍 [Loader] Ejemplo de ID en objeto SKU: '{skus[0].sku_id}' (Tipo: {type(skus[0].sku_id)})")

    # 6. Filtrar órdenes
    filtered_orders = _filter_orders_by_skus(orders, skus, stats)

    return skus, filtered_orders, stats

def load_slotting_inputs(
    codes_csv_path: str | Path,
    orders_csv_path: str | Path,
    cycle_days: float,
    period_days: float = 180.0,
    include_zero_rot: bool = False,
) -> tuple[list[SKU], list[Order]]:
    """Load SKU + Order inputs from CSV files (prep pipeline)."""
    skus, orders, _ = load_slotting_inputs_with_stats(
        codes_csv_path=codes_csv_path,
        orders_csv_path=orders_csv_path,
        cycle_days=cycle_days,
        period_days=period_days,
        include_zero_rot=include_zero_rot,
    )
    return skus, orders

def _build_skus(
    sku_records: dict[str, SkuRecord],
    rot_by_sku: dict[str, int],
    units_by_sku: dict[str, float],
    cycle_days: float,
    period_days: float,
    include_zero_rot: bool,
    stats: PrepStats,
) -> list[SKU]:
    """Build validated SKU objects with cycle units and rotation."""
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
                description=record.description or "",
                boxes_per_m3=record.boxes_per_m3 or 0.0,
                category=record.category or "",
                # -------------------------------
            )
        )
    stats.total_skus_final = len(skus)
    return skus


def _compute_cycle_units(
    units_by_sku: dict[str, float],
    sku_id: str,
    cycle_days: float,
    period_days: float,
) -> float:
    units_per_period = units_by_sku.get(sku_id, 0.0)
    return units_per_period * (cycle_days / period_days)


def _filter_orders_by_skus(
    orders: list[Order],
    skus: list[SKU],
    stats: PrepStats,
) -> list[Order]:
    """Remove SKUs missing from master data and drop empty orders."""
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