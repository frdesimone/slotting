from __future__ import annotations

import pandas as pd
import gc
from collections import defaultdict
from pathlib import Path

from slotting.models import Order
from .stats import OrderLoadStats, DataValidation

def _clean_numeric_col(series):
    # Convertimos a número limpiando comas y forzamos el valor absoluto
    return pd.to_numeric(series.astype(str).str.replace(',', '.'), errors='coerce').abs()

def load_orders_from_pedidos(
    path: str | Path,
    allowed_skus: set[str] | None = None,
    mapping: dict = None, 
    xls: pd.ExcelFile = None, # <-- RECIBE EL EXCEL YA ABIERTO
    excluded_orders: set[str] = None # <-- NUEVO
) -> tuple[list[Order], dict[str, int], dict[str, float], OrderLoadStats]:
    
    if mapping is None: mapping = {}
    if excluded_orders is None: excluded_orders = set()
    path_obj = Path(path)
    stats = OrderLoadStats()
    
    sheet_pedidos = mapping.get("sheet_pedidos", "Pedidos").strip().lower()
    col_pedido_id = mapping.get("col_pedido_id", "Nro pedido").strip().lower()
    col_pedido_sku = mapping.get("col_pedido_sku", "Codigo II - Producto").strip().lower()
    col_pedido_cant = mapping.get("col_pedido_cant", "Cantidad UM de venta").strip().lower()
    col_pedido_fecha = mapping.get("col_pedido_fecha", "Fecha").strip().lower()

    print("📂 [Orders Loader] Procesando órdenes...")

    if path_obj.suffix.lower() in [".xlsx", ".xls"]:
        should_close_xls = False
        if xls is None:
            xls = pd.ExcelFile(path_obj)
            should_close_xls = True
            
        actual_sheet = next((s for s in xls.sheet_names if sheet_pedidos in s.lower()), None)
        if not actual_sheet: actual_sheet = 0
            
        # Buscar cabecera
        df_preview = pd.read_excel(xls, sheet_name=actual_sheet, header=None, nrows=100)
        header_idx = 0
        for i, row in df_preview.iterrows():
            row_str = [str(val).strip().lower() for val in row.values if pd.notna(val)]
            if any(col_pedido_id in k for k in row_str) and any(col_pedido_sku in k for k in row_str):
                header_idx = i
                print(f"   -> [Orders Loader] Cabecera detectada en fila {i} (Excel {i+1}).")
                break
        del df_preview # Limpiar preview
                
        # --- ESTRATEGIA QUIRÚRGICA DE MEMORIA ---
        # 1. Leemos solo la fila de cabecera para ver los nombres EXACTOS de las columnas
        df_cols = pd.read_excel(xls, sheet_name=actual_sheet, header=header_idx, nrows=0)
        exact_cols = df_cols.columns.tolist()
        exact_cols_lower = [str(c).strip().lower() for c in exact_cols]
        
        id_exact = next((c for c, l in zip(exact_cols, exact_cols_lower) if col_pedido_id in l), None)
        sku_exact = next((c for c, l in zip(exact_cols, exact_cols_lower) if col_pedido_sku in l), None)
        cant_exact = next((c for c, l in zip(exact_cols, exact_cols_lower) if col_pedido_cant in l), None)
        fecha_exact = next((c for c, l in zip(exact_cols, exact_cols_lower) if col_pedido_fecha in l), None)
        
        cols_to_use = [c for c in [id_exact, sku_exact, cant_exact, fecha_exact] if c is not None]
        print(f"   -> [Memoria] Cargando SOLO las columnas: {cols_to_use}")

        # 2. Cargamos el Excel COMPLETO, pero limitando drásticamente el uso de RAM
        df = pd.read_excel(xls, sheet_name=actual_sheet, header=header_idx, usecols=cols_to_use)
        
        if should_close_xls:
            xls.close()
    else:
        df = pd.read_csv(path_obj, sep=None, engine='python')

    # Normalizar las columnas que sí trajimos
    df.columns = [str(c).strip().lower() for c in df.columns]

    # Obtenemos los días directamente de la configuración del usuario
    period_days = float(mapping.get("period_days", 180.0))
    if period_days <= 0:
        period_days = 180.0
    stats.period_days = period_days

    fecha_col = next((c for c in df.columns if col_pedido_fecha in c), None)
    id_col = next((c for c in df.columns if col_pedido_id in c), None)
    sku_col = next((c for c in df.columns if col_pedido_sku in c), None)
    cant_col = next((c for c in df.columns if col_pedido_cant in c), None)

    if not id_col or not sku_col:
        raise ValueError(f"Faltan columnas de pedidos. ID='{col_pedido_id}', SKU='{col_pedido_sku}'")

    if cant_col:
        df[cant_col] = _clean_numeric_col(df[cant_col])

    # Reporte de validación
    LOGICAL_COLS_PEDIDOS = [
        ("Nro pedido", id_col),
        ("Código SKU", sku_col),
        ("Cantidad UM de venta", cant_col),
        ("Fecha", fecha_col),
    ]
    found_columns = [name for name, col in LOGICAL_COLS_PEDIDOS if col]
    missing_columns = [name for name, col in LOGICAL_COLS_PEDIDOS if not col]
    sample_data = []
    for _, row in df.head(5).iterrows():
        sample_data.append({
            "Nro pedido": str(row[id_col]) if id_col in row.index else "",
            "Código SKU": str(row[sku_col]) if sku_col in row.index else "",
            "Cantidad UM de venta": row[cant_col] if cant_col and cant_col in row.index else "",
            "Fecha": str(row[fecha_col]) if fecha_col and fecha_col in row.index else "",
        })
    stats.pedidos_validation = DataValidation(
        found_columns=found_columns, missing_columns=missing_columns, sample_data=sample_data
    )

    order_items: dict[str, set[str]] = defaultdict(set)
    rot_by_sku: dict[str, int] = defaultdict(int)
    units_by_sku: dict[str, float] = defaultdict(float)

    for _, row in df.iterrows():
        stats.total_rows += 1
        o_id, s_id = str(row[id_col]).strip(), str(row[sku_col]).strip()

        if o_id in excluded_orders:
            continue

        if not o_id or o_id.lower() in ["nan", "none"] or not s_id or s_id.lower() in ["nan", "none"]:
            stats.skipped_missing_fields += 1
            continue
            
        if allowed_skus is not None and s_id not in allowed_skus:
            stats.skipped_missing_master += 1
            continue

        units = 1.0
        if cant_col and pd.notna(row[cant_col]):
            units = abs(float(row[cant_col]))

        order_items[o_id].add(s_id)
        rot_by_sku[s_id] += 1
        units_by_sku[s_id] += units
        stats.kept_rows += 1

    stats.total_units = sum(units_by_sku.values())
    orders = [Order(order_id=o, sku_ids=sorted(s)) for o, s in order_items.items()]
    stats.total_orders = len(orders)

    # Eliminar el DataFrame gigante
    del df
    gc.collect()

    return orders, rot_by_sku, units_by_sku, stats