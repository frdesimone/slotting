"""
Módulo de carga de Códigos (SKUs) y Maestro de Materiales.
Soporta archivos CSV (Legacy) y Excel (Bremen/SAP) con detección automática de cabecera.
Incluye lógica 'Show Must Go On' para evitar paradas por filtros vacíos.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import pandas as pd
import numpy as np

from .parsing import find_header, parse_float, read_csv_rows
from .stats import DataValidation

# --- DEFINICIÓN DE COLUMNAS ---
COL_CODIGO = "codigo ii"
COL_PROMEDIO = "promedio vta"
COL_M3 = "m3 x unidad"
COL_PESO = "peso [kgrs]"
COL_ALTO = "alto [mm]"
COL_ANCHO = "ancho [mm]"
COL_LARGO = "largo [mm]"
COL_SENSIBLE = "es sensible"
COL_APTO_VLM = "apto vlm"

SHEET_BREMEN = "SLOTTING (trabajado)"
COL_BREMEN_MATERIAL = ["material", "código", "codigo", "sku", "producto"]
COL_BREMEN_KEY_METRICS = ["m3/umb", "kg/umb", "clasificación", "clasificacion"]
COL_BREMEN_CLASIFICACION = "clasificación"
COL_BREMEN_M3 = "m3/umb"
COL_BREMEN_KG = "kg/umb"
COL_BREMEN_KG_SEM = "kg/sem bu1"
COL_BREMEN_ZONA = "zona picking"

@dataclass
class SkuRecord:
    sku_id: str
    avg_units_per_line: float | None
    volume: float | None
    weight: float | None
    height: float | None
    width: float | None
    length: float | None
    is_sensitive: bool = False
    vlm_eligible: bool = True
    source_classification: str | None = None
    demand_kg_sem: float | None = None
    description: str = ""
    boxes_per_m3: float = 0.0
    category: str = ""


def load_sku_records_from_codes(path: str | Path, mapping: dict = None, xls: pd.ExcelFile = None) -> tuple[dict[str, SkuRecord], DataValidation]:
    path = Path(path)
    if mapping is None: mapping = {}
        
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {path}")

    if path.suffix.lower() in [".xlsx", ".xls"]:
        return _load_from_excel_bremen(path, mapping, xls)
    else:
        records = _load_from_csv_generic(path)
        return records, DataValidation()

def _clean_numeric_col(series):
    # Convertimos a número limpiando comas y forzamos el valor absoluto
    return pd.to_numeric(series.astype(str).str.replace(',', '.'), errors='coerce').abs()

def _load_from_excel_bremen(path: Path, mapping: dict, xls: pd.ExcelFile = None) -> tuple[dict[str, SkuRecord], DataValidation]:
    print(f"📂 [Codes Loader] Procesando códigos...")
    
    def clean_text(text):
        return str(text).replace('\n', ' ').replace('\r', '').strip().lower()

    # NUEVO: Limpiador de .0 fantasma de Pandas
    def clean_sku_id(val):
        s = str(val).strip()
        if s.endswith('.0'): return s[:-2]
        return s

    sheet_base = clean_text(mapping.get("sheet_maestro", "Base Cód."))
    col_sku = clean_text(mapping.get("col_sku_maestro", "Material"))
    col_peso = clean_text(mapping.get("col_peso", "Peso (KG)"))
    col_alto = clean_text(mapping.get("col_alto", "Alto (CM)"))
    col_ancho = clean_text(mapping.get("col_ancho", "Ancho (CM)"))
    col_largo = clean_text(mapping.get("col_largo", "Largo (CM)"))
    col_desc = clean_text(mapping.get("col_desc", "Descripción"))
    col_cajas_m3 = clean_text(mapping.get("col_cajas_m3", "UM venta a UM reposición"))
    col_categoria = clean_text(mapping.get("col_categoria", "Categoría"))
    
    should_close_xls = False
    if xls is None:
        xls = pd.ExcelFile(path)
        should_close_xls = True
    
    # --- DIMENSIONES (Por si siguen estando en otra hoja) ---
    dimensions_lookup = {}
    actual_sheet_base = next((s for s in xls.sheet_names if sheet_base in clean_text(s)), None)
    
    if actual_sheet_base:
        try:
            df_dims_preview = pd.read_excel(xls, sheet_name=actual_sheet_base, header=None, nrows=100)
            dim_header_idx = 0
            for i, r in df_dims_preview.iterrows():
                row_str = [clean_text(val) for val in r.values if pd.notna(val)]
                if (any(col_sku in k for k in row_str) or any("material" in k for k in row_str)):
                    dim_header_idx = i
                    break
            del df_dims_preview
            
            df_dims = pd.read_excel(xls, sheet_name=actual_sheet_base, header=dim_header_idx)
            df_dims.columns = [clean_text(c) for c in df_dims.columns]
            dim_id_col = next((c for c in df_dims.columns if col_sku in c), None) or next((c for c in ["material", "código"] if c in df_dims.columns), None)
            c_alto = next((c for c in df_dims.columns if col_alto in c), None)
            c_ancho = next((c for c in df_dims.columns if col_ancho in c), None)
            c_largo = next((c for c in df_dims.columns if col_largo in c), None)
            
            if dim_id_col and c_alto and c_ancho and c_largo:
                for _, row in df_dims.iterrows():
                    sku_str = clean_sku_id(row[dim_id_col]) # Limpiamos ID acá también
                    if not sku_str or sku_str in ["nan", "none"]: continue
                    try:
                        h = abs(float(str(row[c_alto]).replace(',','.')))
                        w = abs(float(str(row[c_ancho]).replace(',','.')))
                        l = abs(float(str(row[c_largo]).replace(',','.')))
                        if h > 0 and w > 0 and l > 0: dimensions_lookup[sku_str] = (h, w, l)
                    except ValueError: pass
            del df_dims
        except Exception:
            pass

    # --- HOJA PRINCIPAL ---
    try:
        sheet_used = "SLOTTING (trabajado)"
        df_preview = pd.read_excel(xls, sheet_name=sheet_used, header=None, nrows=100)
    except Exception:
        sheet_used = 0
        df_preview = pd.read_excel(xls, sheet_name=sheet_used, header=None, nrows=100)

    header_idx = 0
    header_found = False
    for i, row in df_preview.iterrows():
        row_str = [clean_text(val) for val in row.values if pd.notna(val)]
        has_id_exact = any(col_sku == k for k in row_str)
        has_id_sub = any(col_sku in k for k in row_str)
        has_metric = any(col_peso in k for k in row_str)
        if has_id_exact or (has_id_sub and has_metric):
            header_idx = i
            header_found = True
            break
            
    if not header_found:
        print(f"⚠️ [Codes Loader] ALERTA: No se detectó la cabecera en las primeras 100 líneas.")
    del df_preview

    df = pd.read_excel(xls, sheet_name=sheet_used, header=header_idx)
    df.columns = [clean_text(c) for c in df.columns]
    print(f"🔍 [DEBUG] Todas las columnas encontradas en el header: {df.columns.tolist()}")

    def get_col(key_name, default_val):
        val = mapping.get(key_name)
        if val is not None and str(val).strip() == "": return None  # El usuario la dejó vacía
        target = clean_text(val if val is not None else default_val)
        if not target: return None
        # 1. Prioridad: Match exacto
        for c in df.columns:
            if c == target: return c
        # 2. Prioridad: Match parcial
        for c in df.columns:
            if target in c: return c
        return None

    id_col = get_col("col_sku_maestro", "Material") or next((c for c in ["material", "código", "codigo ii"] if c in df.columns), None)
    col_p = get_col("col_peso", "Peso (KG)")
    col_d = get_col("col_desc", "Descripción")
    col_cajas = get_col("col_cajas_m3", "UM venta a UM reposición")
    col_cat = get_col("col_categoria", "Categoría")
    col_main_h = get_col("col_alto", "Alto (CM)")
    col_main_w = get_col("col_ancho", "Ancho (CM)")
    col_main_l = get_col("col_largo", "Largo (CM)")

    def safe_float(val):
        if pd.isna(val) or val is None: return 0.0
        s = str(val).strip()
        match = re.search(r'-?[\d]+(?:[\,\.][\d]+)?', s)
        if not match: return 0.0
        try: return abs(float(match.group(0).replace(',', '.')))
        except ValueError: return 0.0

    def safe_str(val):
        if pd.isna(val) or val is None: return ""
        return str(val).replace('\n', ' ').replace('\r', '').strip()

    records = {}
    for _, row in df.iterrows():
        sku_id = clean_sku_id(row[id_col]) # Limpiamos ID principal
        if not sku_id or sku_id.lower() in ["nan", "none"]: continue

        # Leer dimensiones primero (alto, ancho, largo en cm)
        h = safe_float(row[col_main_h]) if col_main_h else 0.0
        w = safe_float(row[col_main_w]) if col_main_w else 0.0
        l = safe_float(row[col_main_l]) if col_main_l else 0.0
        if h == 0 or w == 0 or l == 0:
            fh, fw, fl = dimensions_lookup.get(sku_id, (0.0, 0.0, 0.0))
            if h == 0: h = fh
            if w == 0: w = fw
            if l == 0: l = fl

        # Volumen calculado: Alto * Ancho * Largo (cm -> m: /100 cada dimensión)
        vol_m3 = (h / 100.0) * (w / 100.0) * (l / 100.0) if (h > 0 and w > 0 and l > 0) else 0.0

        weight_kg = safe_float(row[col_p]) if col_p else 0.0
        description = safe_str(row[col_d]) if col_d else ""
        um_ratio_val = safe_float(row[col_cajas]) if col_cajas else 0.0
        boxes_per_m3 = um_ratio_val if um_ratio_val > 0 else 0.0
        category = safe_str(row[col_cat]) if col_cat else ""

        records[sku_id] = SkuRecord(
            sku_id=sku_id, avg_units_per_line=None, volume=vol_m3, weight=weight_kg,
            height=h, width=w, length=l, is_sensitive=False, vlm_eligible=True, source_classification="BREMEN_XLS",
            description=description, boxes_per_m3=boxes_per_m3, category=category
        )

    # Reporte de validación
    LOGICAL_COLS_MAESTRO = [
        ("Código de SKU", id_col),
        ("Descripción del SKU", col_d),
        ("Peso (kg)", col_p),
        ("Alto (cm)", col_main_h),
        ("Largo (cm)", col_main_l),
        ("Ancho (cm)", col_main_w),
        ("UM venta a UM reposición", col_cajas),
        ("Categoría", col_cat),
    ]
    print("\n🔍 [DEBUG COLUMNAS MAESTRO - MAPEO EXACTO]")
    found_columns = []
    missing_columns = []
    for logical_name, actual_col in LOGICAL_COLS_MAESTRO:
        if actual_col:
            found_columns.append(logical_name)
            print(f"   ✅ {logical_name} -> ENCONTRADA: '{actual_col}'")
        else:
            missing_columns.append(logical_name)
            print(f"   ❌ {logical_name} -> NO ENCONTRADA")
    print("-" * 50)

    sample_data = []
    for _, row in df.head(5).iterrows():
        h_s = safe_float(row.get(col_main_h, 0)) if col_main_h else 0.0
        w_s = safe_float(row.get(col_main_w, 0)) if col_main_w else 0.0
        l_s = safe_float(row.get(col_main_l, 0)) if col_main_l else 0.0
        vol_calc = (h_s / 100.0) * (w_s / 100.0) * (l_s / 100.0) if (h_s > 0 and w_s > 0 and l_s > 0) else 0.0
        sample_data.append({
            "Código de SKU": str(row[id_col]) if id_col and id_col in row.index else "",
            "Descripción del SKU": str(row[col_d]) if col_d and col_d in row.index else "",
            "Volumen Calculado (m3)": vol_calc if (h_s > 0 and w_s > 0 and l_s > 0) else "",
            "Peso (kg)": row[col_p] if col_p and col_p in row.index else "",
            "Alto (cm)": row[col_main_h] if col_main_h and col_main_h in row.index else "",
            "Largo (cm)": row[col_main_l] if col_main_l and col_main_l in row.index else "",
            "Ancho (cm)": row[col_main_w] if col_main_w and col_main_w in row.index else "",
            "UM venta a UM reposición": row[col_cajas] if col_cajas and col_cajas in row.index else "",
            "Categoría": str(row[col_cat]) if col_cat and col_cat in row.index else "",
        })
    validation = DataValidation(found_columns=found_columns, missing_columns=missing_columns, sample_data=sample_data)
        
    if should_close_xls: xls.close()
    del df
    import gc; gc.collect()
        
    return records, validation

def _load_from_csv_generic(path: Path) -> dict[str, SkuRecord]:
    """Carga Legacy CSV"""
    print(f"📄 [CSV Loader] Procesando: {path.name}")
    rows = read_csv_rows(path)
    header_map, data_rows = find_header(
        rows,
        required_headers={COL_CODIGO}, 
        source=str(path),
    )

    records: dict[str, SkuRecord] = {}
    for r in data_rows:
        raw_id = r.get(header_map[COL_CODIGO], "")
        if not raw_id: continue
        sku_id = str(raw_id).strip()
        
        vol = parse_float(r.get(header_map.get(COL_M3), "0"))
        weight = parse_float(r.get(header_map.get(COL_PESO), "0"))
        h = parse_float(r.get(header_map.get(COL_ALTO), "0"))
        w = parse_float(r.get(header_map.get(COL_ANCHO), "0"))
        l = parse_float(r.get(header_map.get(COL_LARGO), "0"))

        if (h == 0 or w == 0 or l == 0) and vol > 0:
            side_mm = (vol ** (1/3)) * 1000.0
            h, w, l = side_mm, side_mm, side_mm

        sens_val = str(r.get(header_map.get(COL_SENSIBLE), "")).lower()
        is_sensitive = sens_val in ["si", "true", "1", "s"]
        
        apto_val = str(r.get(header_map.get(COL_APTO_VLM), "1")).lower()
        vlm_eligible = apto_val not in ["no", "false", "0", "n"]

        record = SkuRecord(
            sku_id=sku_id, avg_units_per_line=None, volume=vol, weight=weight,
            height=h, width=w, length=l, is_sensitive=is_sensitive,
            vlm_eligible=vlm_eligible, source_classification="LEGACY_CSV"
        )
        records[sku_id] = record
    return records