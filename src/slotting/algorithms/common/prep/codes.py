"""
Módulo de carga de Códigos (SKUs) y Maestro de Materiales.
Soporta archivos CSV (Legacy) y Excel (Bremen/SAP) con detección automática de cabecera.
Incluye lógica 'Show Must Go On' para evitar paradas por filtros vacíos.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
import numpy as np

from .parsing import find_header, parse_float, read_csv_rows

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


def load_sku_records_from_codes(path: str | Path, mapping: dict = None, xls: pd.ExcelFile = None) -> dict[str, SkuRecord]:
    path = Path(path)
    if mapping is None: mapping = {}
        
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {path}")

    if path.suffix.lower() in [".xlsx", ".xls"]:
        return _load_from_excel_bremen(path, mapping, xls)
    else:
        return _load_from_csv_generic(path)

def _clean_numeric_col(series):
    # Convertimos a número limpiando comas y forzamos el valor absoluto
    return pd.to_numeric(series.astype(str).str.replace(',', '.'), errors='coerce').abs()

def _load_from_excel_bremen(path: Path, mapping: dict, xls: pd.ExcelFile = None) -> dict[str, SkuRecord]:
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
    col_vol = clean_text(mapping.get("col_volumen", "M3/UMB"))
    col_peso = clean_text(mapping.get("col_peso", "KG/UMB"))
    col_alto = clean_text(mapping.get("col_alto", "Alto"))
    col_ancho = clean_text(mapping.get("col_ancho", "Ancho"))
    col_largo = clean_text(mapping.get("col_largo", "Largo"))
    col_desc = clean_text(mapping.get("col_desc", "Descripción"))
    col_cajas_m3 = clean_text(mapping.get("col_cajas_m3", "Cajas/M3"))
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
        has_metric = any(col_vol in k or col_peso in k for k in row_str)
        if has_id_exact or (has_id_sub and has_metric):
            header_idx = i
            header_found = True
            break
            
    if not header_found:
        print(f"⚠️ [Codes Loader] ALERTA: No se detectó la cabecera en las primeras 100 líneas.")
    del df_preview

    df = pd.read_excel(xls, sheet_name=sheet_used, header=header_idx)
    df.columns = [clean_text(c) for c in df.columns]

    id_col = next((c for c in df.columns if col_sku in c), None) or next((c for c in ["material", "código"] if c in df.columns), None)
    col_v = next((c for c in df.columns if col_vol in c), None)
    col_p = next((c for c in df.columns if col_peso in c), None)
    col_d = next((c for c in df.columns if col_desc in c), None)
    col_cajas = next((c for c in df.columns if col_cajas_m3 in c), None)
    col_cat = next((c for c in df.columns if col_categoria in c), None)
    
    # NUEVO: Buscar las dimensiones directamente en la hoja principal
    col_main_h = next((c for c in df.columns if col_alto in c), None)
    col_main_w = next((c for c in df.columns if col_ancho in c), None)
    col_main_l = next((c for c in df.columns if col_largo in c), None)

    def safe_float(val):
        if pd.isna(val) or val is None: return 0.0
        try: return abs(float(str(val).replace(',', '.').strip()))
        except ValueError: return 0.0

    def safe_str(val):
        if pd.isna(val) or val is None: return ""
        return str(val).replace('\n', ' ').replace('\r', '').strip()

    records = {}
    for _, row in df.iterrows():
        sku_id = clean_sku_id(row[id_col]) # Limpiamos ID principal
        if not sku_id or sku_id.lower() in ["nan", "none"]: continue
            
        vol_m3 = safe_float(row[col_v]) if col_v else 0.0
        weight_kg = safe_float(row[col_p]) if col_p else 0.0
        description = safe_str(row[col_d]) if col_d else ""
        m3_per_box = safe_float(row[col_cajas]) if col_cajas else 0.0
        boxes_per_m3 = (1.0 / m3_per_box) if m3_per_box > 0 else 0.0
        category = safe_str(row[col_cat]) if col_cat else ""
        
        # Lógica de dimensiones independientes: si una falla, las otras se leen igual
        h, w, l = 0.0, 0.0, 0.0
        if col_main_h: h = safe_float(row[col_main_h])
        if col_main_w: w = safe_float(row[col_main_w])
        if col_main_l: l = safe_float(row[col_main_l])
        if h == 0 or w == 0 or l == 0:
            fh, fw, fl = dimensions_lookup.get(sku_id, ((vol_m3**(1/3))*1000 if vol_m3>0 else 0,)*3)
            if h == 0: h = fh
            if w == 0: w = fw
            if l == 0: l = fl

        records[sku_id] = SkuRecord(
            sku_id=sku_id, avg_units_per_line=None, volume=vol_m3, weight=weight_kg,
            height=h, width=w, length=l, is_sensitive=False, vlm_eligible=True, source_classification="BREMEN_XLS",
            description=description, boxes_per_m3=boxes_per_m3, category=category
        )
        
    if should_close_xls: xls.close()
    del df
    import gc; gc.collect()
        
    return records

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