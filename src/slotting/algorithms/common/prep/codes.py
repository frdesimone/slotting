"""
Módulo de carga de Códigos (SKUs) y Maestro de Materiales.
Soporta archivos CSV (Legacy) y Excel (Bremen/SAP).
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from pathlib import Path
import pandas as pd

# Importamos utilidades de parsing existentes
from .parsing import find_header, parse_float, read_csv_rows

# --- DEFINICIÓN DE COLUMNAS ESPERADAS (LEGACY CSV) ---
COL_CODIGO = "codigo ii"
COL_PROMEDIO = "promedio vta"
COL_M3 = "m3 x unidad"
COL_PESO = "peso [kgrs]"
COL_ALTO = "alto [mm]"
COL_ANCHO = "ancho [mm]"
COL_LARGO = "largo [mm]"
COL_SENSIBLE = "es sensible"
COL_APTO_VLM = "apto vlm"

# --- DEFINICIÓN DE COLUMNAS ESPERADAS (EXCEL BREMEN) ---
SHEET_BREMEN = "SLOTTING (trabajado)"
COL_BREMEN_MATERIAL = ["material", "código", "codigo", "sku", "producto"]
COL_BREMEN_CLASIFICACION = "clasificación"
COL_BREMEN_M3 = "m3/umb"
COL_BREMEN_KG = "kg/umb"
COL_BREMEN_KG_SEM = "kg/sem bu1"
COL_BREMEN_ZONA = "zona picking"

@dataclass
class SkuRecord:
    """
    Representación unificada de un registro de SKU proveniente del maestro.
    """
    sku_id: str
    avg_units_per_line: float | None
    volume: float | None      # En m3
    weight: float | None      # En kg
    height: float | None      # En mm
    width: float | None       # En mm
    length: float | None      # En mm
    is_sensitive: bool = False
    vlm_eligible: bool = True
    # Metadatos extra
    source_classification: str | None = None
    demand_kg_sem: float | None = None

def load_sku_records_from_codes(path: str | Path) -> dict[str, SkuRecord]:
    """
    Punto de entrada principal. Detecta formato y carga SKUs.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de códigos: {path}")

    # Detección de formato
    if path.suffix.lower() in [".xlsx", ".xls"]:
        return _load_from_excel_bremen(path)
    else:
        return _load_from_csv_generic(path)

def _load_from_excel_bremen(path: Path) -> dict[str, SkuRecord]:
    """
    Carga específica para el Excel de Bremen con reglas de negocio.
    """
    print(f"📂 [Excel Loader] Procesando: {path.name}")
    
    # 1. Cargar Excel
    try:
        df = pd.read_excel(path, sheet_name=SHEET_BREMEN)
        print(f"   -> Hoja '{SHEET_BREMEN}' encontrada.")
    except Exception:
        print(f"⚠️  No se encontró la hoja '{SHEET_BREMEN}', intentando con la primera hoja disponible.")
        df = pd.read_excel(path, sheet_name=0)

    total_rows = len(df)
    
    # 2. Normalizar columnas (strip y lower)
    df.columns = [str(c).strip().lower() for c in df.columns]

    # 3. Validar columnas críticas
    # Buscar cuál es la columna de ID
    id_col = next((c for c in COL_BREMEN_MATERIAL if c in df.columns), None)
    if not id_col:
        # Si no encuentra 'material', imprime las columnas para ayudar a debuggear
        raise ValueError(f"No se encontró columna de ID (Material). Columnas disponibles: {list(df.columns)}")

    # 4. APLICACIÓN DE REGLAS DE NEGOCIO (FILTROS)
    
    # A. Filtro Clasificación: Solo vacíos (o nulos)
    if COL_BREMEN_CLASIFICACION in df.columns:
        # isna() agarra NaN/None. str.strip()=="" agarra celdas con espacios vacíos
        df = df[df[COL_BREMEN_CLASIFICACION].isna() | (df[COL_BREMEN_CLASIFICACION].astype(str).str.strip() == "")]
    
    # B. M3/UMB: Numérico y > 0
    if COL_BREMEN_M3 in df.columns:
        df[COL_BREMEN_M3] = pd.to_numeric(df[COL_BREMEN_M3], errors='coerce')
        df = df[df[COL_BREMEN_M3] > 0]
    else:
        print(f"⚠️  Advertencia: No se encontró columna '{COL_BREMEN_M3}'. Se asumirá volumen 0.")

    # C. KG/UMB: Numérico, > 0 y <= 1.0 kg
    if COL_BREMEN_KG in df.columns:
        df[COL_BREMEN_KG] = pd.to_numeric(df[COL_BREMEN_KG], errors='coerce')
        # Filtro duro solicitado
        df = df[(df[COL_BREMEN_KG] > 0) & (df[COL_BREMEN_KG] <= 1.0)]
    
    aptos_rows = len(df)
    print(f"✅ [Filtros] Registros aptos para VLM: {aptos_rows} (de {total_rows} originales).")
    print(f"   -> Descartados: {total_rows - aptos_rows} (por Peso > 1kg, Clasificación no vacía o Volumen 0)")

    # 5. Construcción de Objetos
    records: dict[str, SkuRecord] = {}
    
    for _, row in df.iterrows():
        sku_id = str(row[id_col]).strip()
        # Validación básica de ID
        if not sku_id or sku_id.lower() in ["nan", "none", "nat"]:
            continue
            
        vol_m3 = float(row.get(COL_BREMEN_M3, 0.0))
        weight_kg = float(row.get(COL_BREMEN_KG, 0.0))
        demand_sem = float(row.get(COL_BREMEN_KG_SEM, 0.0)) if COL_BREMEN_KG_SEM in df.columns else None

        # ESTIMACIÓN DE DIMENSIONES (IMPORTANTE)
        # El algoritmo de VLM necesita mm para calcular el stack.
        # Si solo tenemos volumen (m3), asumimos un cubo perfecto.
        # Lado (m) = raiz_cubica(Vol)
        # Lado (mm) = Lado (m) * 1000
        if vol_m3 > 0:
            side_m = vol_m3 ** (1/3)
            side_mm = side_m * 1000.0
        else:
            side_mm = 0.0

        record = SkuRecord(
            sku_id=sku_id,
            avg_units_per_line=None, # Se completará con el archivo de Pedidos
            volume=vol_m3,
            weight=weight_kg,
            height=side_mm, # Estimado
            width=side_mm,  # Estimado
            length=side_mm, # Estimado
            is_sensitive=False, # Bremen no especificó columna de sensibilidad, asumimos False
            vlm_eligible=True,  # Ya filtramos los false
            demand_kg_sem=demand_sem,
            source_classification="BREMEN_XLS"
        )
        records[sku_id] = record
        
    return records

def _load_from_csv_generic(path: Path) -> dict[str, SkuRecord]:
    """
    Carga Genérica CSV (Legacy) para tests y archivos estándar.
    """
    print(f"📄 [CSV Loader] Procesando: {path.name}")
    rows = read_csv_rows(path)
    
    # Mapeo de columnas
    header_map, data_rows = find_header(
        rows,
        required_headers={COL_CODIGO}, # Mínimo necesario
        source=str(path),
    )

    records: dict[str, SkuRecord] = {}
    for r in data_rows:
        # Extraer ID
        raw_id = r.get(header_map[COL_CODIGO], "")
        if not raw_id:
            continue
        
        sku_id = str(raw_id).strip()

        # Parsear métricas numéricas
        vol = parse_float(r.get(header_map.get(COL_M3), "0"))
        weight = parse_float(r.get(header_map.get(COL_PESO), "0"))
        
        # Dimensiones (si el CSV las trae, suelen venir en mm)
        h = parse_float(r.get(header_map.get(COL_ALTO), "0"))
        w = parse_float(r.get(header_map.get(COL_ANCHO), "0"))
        l = parse_float(r.get(header_map.get(COL_LARGO), "0"))

        # Si no hay dimensiones pero hay volumen, estimar (fallback)
        if (h == 0 or w == 0 or l == 0) and vol > 0:
            side_mm = (vol ** (1/3)) * 1000.0
            h, w, l = side_mm, side_mm, side_mm

        # Flags booleanos
        # "Es sensible" -> 'si'/'true'/1
        sens_val = str(r.get(header_map.get(COL_SENSIBLE), "")).lower()
        is_sensitive = sens_val in ["si", "true", "1", "s"]

        # "Apto VLM"
        apto_val = str(r.get(header_map.get(COL_APTO_VLM), "1")).lower() # Default True
        vlm_eligible = apto_val not in ["no", "false", "0", "n"]

        record = SkuRecord(
            sku_id=sku_id,
            avg_units_per_line=None,
            volume=vol,
            weight=weight,
            height=h,
            width=w,
            length=l,
            is_sensitive=is_sensitive,
            vlm_eligible=vlm_eligible,
            source_classification="LEGACY_CSV"
        )
        records[sku_id] = record

    print(f"✅ [CSV] SKUs cargados: {len(records)}")
    return records