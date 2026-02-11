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

def load_sku_records_from_codes(path: str | Path) -> dict[str, SkuRecord]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de códigos: {path}")

    if path.suffix.lower() in [".xlsx", ".xls"]:
        return _load_from_excel_bremen(path)
    else:
        return _load_from_csv_generic(path)

def _clean_numeric_col(series):
    """Convierte columna a numérico soportando comas decimales."""
    return pd.to_numeric(series.astype(str).str.replace(',', '.'), errors='coerce')

def _load_from_excel_bremen(path: Path) -> dict[str, SkuRecord]:
    print(f"📂 [Excel Loader] Procesando: {path.name}")
    
    # 1. Detección de Hoja y Cabecera
    try:
        df_preview = pd.read_excel(path, sheet_name=SHEET_BREMEN, header=None, nrows=20)
        sheet_used = SHEET_BREMEN
    except Exception:
        print(f"⚠️  No se encontró la hoja '{SHEET_BREMEN}', leyendo la primera hoja disponible.")
        df_preview = pd.read_excel(path, sheet_name=0, header=None, nrows=20)
        sheet_used = 0

    header_idx = None
    for i, row in df_preview.iterrows():
        row_str = [str(val).strip().lower() for val in row.values if pd.notna(val)]
        has_id = any(k in row_str for k in COL_BREMEN_MATERIAL)
        has_metric = any(k in row_str for k in COL_BREMEN_KEY_METRICS)
        
        if has_id and has_metric:
            header_idx = i
            print(f"   -> Cabecera detectada en la fila {i} (Excel row {i+1}).")
            break
            
    if header_idx is None:
        print("⚠️  No se detectó automáticamente la fila de cabecera. Usando fila 0.")
        header_idx = 0

    # 2. Cargar DataFrame
    df = pd.read_excel(path, sheet_name=sheet_used, header=header_idx)
    df.columns = [str(c).strip().lower() for c in df.columns]

    id_col = next((c for c in COL_BREMEN_MATERIAL if c in df.columns), None)
    if not id_col:
        raise ValueError(f"No se encontró columna 'Material'. Columnas: {list(df.columns)}")

    total_rows = len(df)
    print(f"   -> Filas leídas inicialmente: {total_rows}")

    # 4. FILTROS CON SEGURIDAD (Show Must Go On)
    
    # A. Filtro Clasificación
    if COL_BREMEN_CLASIFICACION in df.columns:
        # Debug: Mostrar qué hay en la columna antes de filtrar
        sample_vals = df[COL_BREMEN_CLASIFICACION].unique()[:5]
        print(f"   -> [Debug] Valores en '{COL_BREMEN_CLASIFICACION}': {sample_vals}")
        
        df_filtered = df.copy()
        df_filtered[COL_BREMEN_CLASIFICACION] = df_filtered[COL_BREMEN_CLASIFICACION].astype(str).str.strip().str.lower()
        df_filtered = df_filtered[df_filtered[COL_BREMEN_CLASIFICACION].isin(['nan', 'none', '', 'nat'])]
        
        if len(df_filtered) == 0 and len(df) > 0:
            print(f"⚠️  [ALERTA] El filtro de Clasificación eliminó TODOS los registros.")
            print(f"   -> IGNORANDO FILTRO para permitir la demo. Se usarán todos los items.")
        else:
            df = df_filtered
            print(f"   -> [Filtro Clasificación] Restan: {len(df)}")
    
    # B. M3/UMB
    if COL_BREMEN_M3 in df.columns:
        df_filtered = df.copy()
        df_filtered[COL_BREMEN_M3] = _clean_numeric_col(df_filtered[COL_BREMEN_M3])
        df_filtered = df_filtered[df_filtered[COL_BREMEN_M3] > 0]
        
        if len(df_filtered) == 0 and len(df) > 0:
            print(f"⚠️  [ALERTA] El filtro de Volumen eliminó TODOS los registros.")
            print(f"   -> IGNORANDO FILTRO (Asumiendo volúmenes por defecto o revisión manual).")
        else:
            df = df_filtered
            print(f"   -> [Filtro M3 > 0] Restan: {len(df)}")

    # C. KG/UMB
    if COL_BREMEN_KG in df.columns:
        df_filtered = df.copy()
        df_filtered[COL_BREMEN_KG] = _clean_numeric_col(df_filtered[COL_BREMEN_KG])
        # Debug Pesos
        # print(f"DEBUG PESOS: {df_filtered[COL_BREMEN_KG].describe()}")
        df_filtered = df_filtered[(df_filtered[COL_BREMEN_KG] > 0) & (df_filtered[COL_BREMEN_KG] <= 1.0)]
        
        if len(df_filtered) == 0 and len(df) > 0:
             print(f"⚠️  [ALERTA] El filtro de Peso (<=1kg) eliminó TODOS los registros.")
             print(f"   -> IGNORANDO FILTRO para permitir la demo.")
        else:
             df = df_filtered
             print(f"   -> [Filtro Peso <= 1kg] Restan: {len(df)}")
    
    print(f"✅ [Final] Registros aptos para VLM: {len(df)}")

    # 5. Construcción de Objetos
    records: dict[str, SkuRecord] = {}
    
    for _, row in df.iterrows():
        sku_id = str(row[id_col]).strip()
        if not sku_id or sku_id.lower() in ["nan", "none"]:
            continue
            
        vol_m3 = float(row.get(COL_BREMEN_M3, 0.0))
        # Si el volumen falló en convertirse a float antes, nos aseguramos aquí
        if pd.isna(vol_m3): vol_m3 = 0.0

        weight_kg = float(row.get(COL_BREMEN_KG, 0.0))
        if pd.isna(weight_kg): weight_kg = 0.0

        demand_sem = float(row.get(COL_BREMEN_KG_SEM, 0.0)) if COL_BREMEN_KG_SEM in df.columns else None

        if vol_m3 > 0:
            side_m = vol_m3 ** (1/3)
            side_mm = side_m * 1000.0
        else:
            side_mm = 0.0

        record = SkuRecord(
            sku_id=sku_id,
            avg_units_per_line=None, 
            volume=vol_m3,
            weight=weight_kg,
            height=side_mm,
            width=side_mm,
            length=side_mm,
            is_sensitive=False,
            vlm_eligible=True,
            demand_kg_sem=demand_sem,
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