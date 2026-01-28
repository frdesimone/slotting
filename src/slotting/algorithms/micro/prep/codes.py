from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .parsing import find_header, parse_float, parse_sku_id, read_csv_rows


@dataclass
class SkuRecord:
    sku_id: str
    avg_units_per_line: float | None
    volume: float | None
    weight: float | None
    height: float | None
    width: float | None
    length: float | None


def load_sku_records_from_codes(
    path: str | Path,
) -> dict[str, SkuRecord]:
    rows = read_csv_rows(path)
    header_map, data_rows = find_header(
        rows,
        required_headers={
            "codigo ii",
            "promedio vta",
            "m3 x unidad",
            "peso [kgrs]",
            "alto [mm]",
            "ancho [mm]",
            "largo [mm]",
        },
        source=str(path),
    )

    records: dict[str, SkuRecord] = {}
    for row in data_rows:
        sku_id = parse_sku_id(row[header_map["codigo ii"]])
        if not sku_id:
            continue

        record = SkuRecord(
            sku_id=sku_id,
            avg_units_per_line=parse_float(row[header_map["promedio vta"]]),
            volume=parse_float(row[header_map["m3 x unidad"]]),
            weight=parse_float(row[header_map["peso [kgrs]"]]),
            height=parse_float(row[header_map["alto [mm]"]]),
            width=parse_float(row[header_map["ancho [mm]"]]),
            length=parse_float(row[header_map["largo [mm]"]]),
        )

        existing = records.get(sku_id)
        if existing is None:
            records[sku_id] = record
        else:
            merge_sku_record(existing, record)

    for record in records.values():
        if record.volume is None:
            record.volume = derive_volume_from_mm(
                record.height,
                record.width,
                record.length,
            )

    return records


def merge_sku_record(base: SkuRecord, other: SkuRecord) -> None:
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


def derive_volume_from_mm(
    height_mm: float | None,
    width_mm: float | None,
    length_mm: float | None,
) -> float | None:
    if height_mm is None or width_mm is None or length_mm is None:
        return None
    return (height_mm / 1000.0) * (width_mm / 1000.0) * (length_mm / 1000.0)
