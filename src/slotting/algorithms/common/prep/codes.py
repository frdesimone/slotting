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

def load_sku_records_from_codes(path: str | Path, mapping: dict = None) -> dict[str, SkuRecord]:
    path = Path(path)
    if mapping is None:
        mapping = {}
        
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de códigos: {path}")

    if path.suffix.lower() in [".xlsx", ".xls"]:
        return _load_from_excel_bremen(path, mapping) # <-- Pasamos el mapping
    else:
        # Si quisieras adaptar el CSV luego, también le podés pasar el mapping
        return _load_from_csv_generic(path)

def _clean_numeric_col(series):
    """Convierte columna a numérico soportando comas decimales."""
    return pd.to_numeric(series.astype(str).str.replace(',', '.'), errors='coerce')

def _load_from_excel_bremen(path: Path, mapping: dict) -> dict[str, SkuRecord]:
    print(f"📂 [Excel Loader] Procesando: {path.name}")
    
    # Extraemos los nombres dinámicos, los limpiamos de espacios y los pasamos a minúscula
    sheet_base = mapping.get("sheet_maestro", "Base Cód.").strip().lower()
    col_sku = mapping.get("col_sku_maestro", "Material").strip().lower()
    col_vol = mapping.get("col_volumen", "M3/UMB").strip().lower()
    col_peso = mapping.get("col_peso", "KG/UMB").strip().lower()
    col_alto = mapping.get("col_alto", "Alto").strip().lower()
    col_ancho = mapping.get("col_ancho", "Ancho").strip().lower()
    col_largo = mapping.get("col_largo", "Largo").strip().lower()
    
    # --- EXTRAER DIMENSIONES REALES ---
    dimensions_lookup = {}
    try:
        xls = pd.ExcelFile(path)
        # Buscar la hoja coincidiendo con el nombre dinámico del mapping
        actual_sheet_base = next((s for s in xls.sheet_names if sheet_base in s.lower()), None)
        
        if actual_sheet_base:
            df_dims_preview = pd.read_excel(xls, sheet_name=actual_sheet_base, header=None, nrows=15)
            dim_header_idx = 0
            for i, r in df_dims_preview.iterrows():
                row_str = [str(val).strip().lower() for val in r.values if pd.notna(val)]
                
                # Buscamos si la fila contiene nuestra columna dinámica de SKU y Alto
                has_id = any(col_sku in k for k in row_str) or any("material" in k for k in row_str)
                has_alto = any(col_alto in k for k in row_str) or any("alto" in k for k in row_str)
                
                if has_id and has_alto:
                    dim_header_idx = i
                    break
            
            df_dims = pd.read_excel(xls, sheet_name=actual_sheet_base, header=dim_header_idx)
            df_dims.columns = [str(c).strip().lower() for c in df_dims.columns]
            
            # Matcheamos las columnas con las que definió el usuario
            dim_id_col = next((c for c in df_dims.columns if col_sku in c), None)
            if not dim_id_col: # Fallback de seguridad
                dim_id_col = next((c for c in ["material", "código", "codigo ii"] if c in df_dims.columns), None)
                
            c_alto = next((c for c in df.columns if col_alto in c), None) if 'df' in locals() else next((c for c in df_dims.columns if col_alto in c), None)
            c_ancho = next((c for c in df_dims.columns if col_ancho in c), None)
            c_largo = next((c for c in df_dims.columns if col_largo in c), None)
            
            if dim_id_col and c_alto and c_ancho and c_largo:
                for _, row in df_dims.iterrows():
                    sku_str = str(row[dim_id_col]).strip()
                    if not sku_str or sku_str in ["nan", "none"]: continue
                    try:
                        h = float(str(row[c_alto]).replace(',', '.'))
                        w = float(str(row[c_ancho]).replace(',', '.'))
                        l = float(str(row[c_largo]).replace(',', '.'))
                        if h > 0 and w > 0 and l > 0:
                            dimensions_lookup[sku_str] = (h, w, l)
                    except ValueError:
                        pass
                print(f"   -> [Dimensiones] Extraídas dimensiones de '{actual_sheet_base}' para {len(dimensions_lookup)} SKUs.")
    except Exception as e:
        print(f"⚠️  No se pudieron extraer dimensiones de la hoja base: {e}")

    # --- LECTURA DE HOJA PRINCIPAL ---
    # Asumimos que la hoja de trabajo siempre tiene la data si la anterior era la "Base"
    try:
        # Intentamos la por defecto, o la primera si no la encontramos
        df_preview = pd.read_excel(path, sheet_name="SLOTTING (trabajado)", header=None, nrows=20)
        sheet_used = "SLOTTING (trabajado)"
    except Exception:
        df_preview = pd.read_excel(path, sheet_name=0, header=None, nrows=20)
        sheet_used = 0

    header_idx = 0
    for i, row in df_preview.iterrows():
        row_str = [str(val).strip().lower() for val in row.values if pd.notna(val)]
        has_id = any(col_sku in k for k in row_str) or any("material" in k for k in row_str)
        has_metric = any(col_vol in k or col_peso in k for k in row_str)
        if has_id and has_metric:
            header_idx = i
            break

    df = pd.read_excel(path, sheet_name=sheet_used, header=header_idx)
    df.columns = [str(c).strip().lower() for c in df.columns]

    id_col = next((c for c in df.columns if col_sku in c), None)
    if not id_col:
        id_col = next((c for c in ["material", "código", "codigo ii"] if c in df.columns), None)
        if not id_col:
            raise ValueError(f"No se encontró columna para el ID (Buscando: {col_sku}). Columnas disponibles: {list(df.columns)}")

    # Identificamos las columnas numéricas
    found_col_vol = next((c for c in df.columns if col_vol in c), None)
    found_col_peso = next((c for c in df.columns if col_peso in c), None)

    # Filtros de seguridad
    if found_col_vol:
        df_filtered = df.copy()
        df_filtered[found_col_vol] = _clean_numeric_col(df_filtered[found_col_vol])
        df_filtered = df_filtered[df_filtered[found_col_vol] > 0]
        if len(df_filtered) > 0: df = df_filtered

    if found_col_peso:
        df_filtered = df.copy()
        df_filtered[found_col_peso] = _clean_numeric_col(df_filtered[found_col_peso])
        df_filtered = df_filtered[(df_filtered[found_col_peso] > 0) & (df_filtered[found_col_peso] <= 1.0)]
        if len(df_filtered) > 0: df = df_filtered

    # Construcción de Objetos
    records: dict[str, SkuRecord] = {}
    for _, row in df.iterrows():
        sku_id = str(row[id_col]).strip()
        if not sku_id or sku_id.lower() in ["nan", "none"]: continue
            
        vol_m3 = float(row.get(found_col_vol, 0.0)) if found_col_vol else 0.0
        if pd.isna(vol_m3): vol_m3 = 0.0

        weight_kg = float(row.get(found_col_peso, 0.0)) if found_col_peso else 0.0
        if pd.isna(weight_kg): weight_kg = 0.0

        if sku_id in dimensions_lookup:
            h, w, l = dimensions_lookup[sku_id]
        elif vol_m3 > 0:
            side_m = vol_m3 ** (1/3)
            side_mm = side_m * 1000.0
            h = w = l = side_mm
        else:
            h = w = l = 0.0

        record = SkuRecord(
            sku_id=sku_id,
            avg_units_per_line=None, 
            volume=vol_m3,
            weight=weight_kg,
            height=h,
            width=w,
            length=l,
            is_sensitive=False,
            vlm_eligible=True,
            source_classification="BREMEN_XLS"
        )
        records[sku_id] = record
        
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