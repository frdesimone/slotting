from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .parsing import find_header, parse_float, parse_sku_id, read_csv_rows

# Definimos los nombres de columna esperados como constantes
COL_CODIGO = "codigo ii"
COL_PROMEDIO = "promedio vta"
COL_M3 = "m3 x unidad"
COL_PESO = "peso [kgrs]"
COL_ALTO = "alto [mm]"
COL_ANCHO = "ancho [mm]"
COL_LARGO = "largo [mm]"
COL_SENSIBLE = "es sensible"
COL_APTO_VLM = "apto vlm"


@dataclass
class SkuRecord:
    sku_id: str
    avg_units_per_line: float | None
    volume: float | None
    weight: float | None
    height: float | None
    width: float | None
    length: float | None
    # Nuevos campos para Macro-slotting
    is_sensitive: bool = False
    vlm_eligible: bool = True


def load_sku_records_from_codes(
    path: str | Path,
) -> dict[str, SkuRecord]:
    rows = read_csv_rows(path)
    
    # Buscamos todas las columnas necesarias.
    header_map, data_rows = find_header(
        rows,
        required_headers={
            COL_CODIGO,
            COL_PROMEDIO,
            COL_M3,
            COL_PESO,
            COL_ALTO,
            COL_ANCHO,
            COL_LARGO,
            COL_SENSIBLE,
            COL_APTO_VLM,
        },
        source=str(path),
    )

    records: dict[str, SkuRecord] = {}
    for row in data_rows:
        # Usamos el índice del mapa para acceder a la lista row
        sku_id = parse_sku_id(row[header_map[COL_CODIGO]])
        if not sku_id:
            continue
        
        # --- CORRECCIÓN AQUÍ ---
        # Acceso seguro a la lista usando índices, no .get()
        
        # 1. Es Sensible
        idx_sensitive = header_map[COL_SENSIBLE]
        # Protección por si la fila está truncada (raro pero posible)
        raw_sensitive = row[idx_sensitive] if idx_sensitive < len(row) else ""
        is_sensitive = _parse_bool(raw_sensitive, default=False)
        
        # 2. Apto VLM
        idx_eligible = header_map[COL_APTO_VLM]
        raw_eligible = row[idx_eligible] if idx_eligible < len(row) else ""
        # Lógica inversa: es eligible salvo que diga explícitamente que no
        vlm_eligible = not _parse_bool_negative(raw_eligible)
        # -----------------------

        record = SkuRecord(
            sku_id=sku_id,
            avg_units_per_line=parse_float(row[header_map[COL_PROMEDIO]]),
            volume=parse_float(row[header_map[COL_M3]]),
            weight=parse_float(row[header_map[COL_PESO]]),
            height=parse_float(row[header_map[COL_ALTO]]),
            width=parse_float(row[header_map[COL_ANCHO]]),
            length=parse_float(row[header_map[COL_LARGO]]),
            is_sensitive=is_sensitive,
            vlm_eligible=vlm_eligible,
        )

        existing = records.get(sku_id)
        if existing is None:
            records[sku_id] = record
        else:
            merge_sku_record(existing, record)

    # Post-procesamiento: calcular volumen si falta
    for record in records.values():
        if record.volume is None:
            record.volume = derive_volume_from_mm(
                record.height,
                record.width,
                record.length,
            )

    return records


def merge_sku_record(base: SkuRecord, other: SkuRecord) -> None:
    """Combina datos de registros duplicados completando valores faltantes."""
    if base.avg_units_per_line is None and other.avg_units_per_line is not None:
        base.avg_units_per_line = other.avg_units_per_line
    if base.volume is None and other.volume is not None:
        base.volume = other.volume
    if base.weight is None and other.weight is not None:
        base.weight = other.weight
    if base.height is None and other.height is not None:
        base.height = other.height
    if base.width is None and other.width is not None:
        base.width = other.width
    if base.length is None and other.length is not None:
        base.length = other.length
    
    # Merge de flags
    if other.is_sensitive:
        base.is_sensitive = True
    if not other.vlm_eligible:
        base.vlm_eligible = False


def derive_volume_from_mm(
    height_mm: float | None,
    width_mm: float | None,
    length_mm: float | None,
) -> float | None:
    if height_mm is None or width_mm is None or length_mm is None:
        return None
    return (height_mm / 1000.0) * (width_mm / 1000.0) * (length_mm / 1000.0)


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """Devuelve True si el valor es 'SI', 'TRUE', '1', 'YES'."""
    if not value:
        return default
    normalized = value.strip().upper()
    return normalized in ("SI", "S", "TRUE", "T", "YES", "Y", "1")


def _parse_bool_negative(value: str | None) -> bool:
    """Devuelve True si el valor indica negación ('NO', 'FALSE', '0')."""
    if not value:
        return False
    normalized = value.strip().upper()
    return normalized in ("NO", "N", "FALSE", "F", "0")