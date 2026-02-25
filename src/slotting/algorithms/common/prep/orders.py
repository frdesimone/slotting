from __future__ import annotations

import pandas as pd
from collections import defaultdict
from pathlib import Path

from slotting.models import Order
from .stats import OrderLoadStats

def _clean_numeric_col(series):
    """Convierte columna a numérico soportando comas decimales."""
    return pd.to_numeric(series.astype(str).str.replace(',', '.'), errors='coerce')

def load_orders_from_pedidos(
    path: str | Path,
    allowed_skus: set[str] | None = None,
    mapping: dict = None, 
) -> tuple[list[Order], dict[str, int], dict[str, float], OrderLoadStats]:
    """Load orders from Excel/CSV and compute per-SKU rotation + units."""
    
    if mapping is None:
        mapping = {}
        
    path_obj = Path(path)
    stats = OrderLoadStats()
    
    # 1. Extraer nombres dinámicos del mapeo
    sheet_pedidos = mapping.get("sheet_pedidos", "Pedidos").strip().lower()
    col_pedido_id = mapping.get("col_pedido_id", "Nro pedido").strip().lower()
    col_pedido_sku = mapping.get("col_pedido_sku", "Codigo II - Producto").strip().lower()
    col_pedido_cant = mapping.get("col_pedido_cant", "Cantidad unidades").strip().lower()

    print(f"📂 [Orders Loader] Procesando: {path_obj.name}")

    # 2. Cargar DataFrame con detección automática de hoja y cabecera
    if path_obj.suffix.lower() in [".xlsx", ".xls"]:
        xls = pd.ExcelFile(path_obj)
        
        # Buscar la hoja que coincida con el nombre dinámico
        actual_sheet = next((s for s in xls.sheet_names if sheet_pedidos in s.lower()), None)
        if not actual_sheet:
            actual_sheet = 0 # Fallback a la primera hoja disponible
            print(f"⚠️  No se encontró la hoja '{sheet_pedidos}', leyendo la primera disponible.")
            
        # --- BUSCADOR DE CABECERAS PROFUNDO (100 FILAS) ---
        df_preview = pd.read_excel(xls, sheet_name=actual_sheet, header=None, nrows=100)
        header_idx = 0
        header_found = False
        
        for i, row in df_preview.iterrows():
            row_str = [str(val).strip().lower() for val in row.values if pd.notna(val)]
            has_id = any(col_pedido_id in k for k in row_str)
            has_sku = any(col_pedido_sku in k for k in row_str)
            
            if has_id and has_sku:
                header_idx = i
                header_found = True
                print(f"   -> [Orders Loader] Cabecera detectada en la fila {i} (Fila Excel {i+1}).")
                break
                
        if not header_found:
            print(f"⚠️  [ALERTA] No se detectó la cabecera en las primeras 100 líneas.")
            print(f"   Buscábamos: ID='{col_pedido_id}', SKU='{col_pedido_sku}'")
            print(f"   Usando fila 0 por defecto.")
        # -------------------------------------------------
                
        df = pd.read_excel(xls, sheet_name=actual_sheet, header=header_idx)
    else:
        # Fallback de seguridad por si en el futuro vuelven a subir un CSV
        df = pd.read_csv(path_obj, sep=None, engine='python')

    # 3. Normalizar columnas
    df.columns = [str(c).strip().lower() for c in df.columns]

    # Identificar las columnas reales
    id_col = next((c for c in df.columns if col_pedido_id in c), None)
    sku_col = next((c for c in df.columns if col_pedido_sku in c), None)
    cant_col = next((c for c in df.columns if col_pedido_cant in c), None)

    if not id_col or not sku_col:
        raise ValueError(f"No se encontraron las columnas requeridas para pedidos.\nBuscando ID='{col_pedido_id}', SKU='{col_pedido_sku}'.\nColumnas disponibles: {list(df.columns)}")

    # Limpiar cantidad de posibles comas o textos raros
    if cant_col:
        df[cant_col] = _clean_numeric_col(df[cant_col])

    # 4. Procesar Filas
    order_items: dict[str, set[str]] = defaultdict(set)
    rot_by_sku: dict[str, int] = defaultdict(int)
    units_by_sku: dict[str, float] = defaultdict(float)

    for _, row in df.iterrows():
        stats.total_rows += 1
        
        # Extraer y limpiar
        o_id = str(row[id_col]).strip()
        s_id = str(row[sku_col]).strip()

        if not o_id or o_id.lower() in ["nan", "none"] or not s_id or s_id.lower() in ["nan", "none"]:
            stats.skipped_missing_fields += 1
            continue
            
        if allowed_skus is not None and s_id not in allowed_skus:
            stats.skipped_missing_master += 1
            continue

        # Leer cantidad (asumimos 1.0 si falla o no está la columna)
        units = 1.0
        if cant_col and pd.notna(row[cant_col]):
            units = float(row[cant_col])

        # Guardar en las estructuras
        order_items[o_id].add(s_id)
        rot_by_sku[s_id] += 1
        units_by_sku[s_id] += units
        stats.kept_rows += 1

    # 5. Generar lista final de órdenes
    orders = [
        Order(order_id=order_id, sku_ids=sorted(sku_ids))
        for order_id, sku_ids in order_items.items()
    ]
    stats.total_orders = len(orders)

    return orders, rot_by_sku, units_by_sku, stats