from __future__ import annotations

import csv
from pathlib import Path
import unicodedata


def read_csv_rows(path: str | Path) -> list[list[str]]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    with path.open("r", newline="", encoding="utf-8-sig", errors="replace") as handle:
        return list(csv.reader(handle))


def find_header(
    rows: list[list[str]],
    required_headers: set[str],
    source: str,
) -> tuple[dict[str, int], list[list[str]]]:
    for index, row in enumerate(rows):
        header_map = {}
        for col_index, value in enumerate(row):
            header = normalize_header(value)
            if header:
                header_map[header] = col_index
        if required_headers.issubset(header_map.keys()):
            return header_map, rows[index + 1 :]
    available = sorted(
        {header for row in rows for header in (normalize_header(v) for v in row) if header}
    )
    raise ValueError(
        f"Missing required headers in {source}: {sorted(required_headers)}; "
        f"found {available}"
    )


def normalize_header(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.strip().lower().split())


def parse_cell(value: str) -> str | None:
    cleaned = value.strip() if value else ""
    if not cleaned:
        return None
    return cleaned


def parse_sku_id(value: str) -> str | None:
    if not value:
        return None
    cleaned = value.replace(",", "").strip()
    if not cleaned or cleaned in {"-", "#VALUE!", "#N/A"}:
        return None
    return cleaned


def parse_float(value: str) -> float | None:
    if not value:
        return None
    cleaned = value.replace(",", "").strip()
    if not cleaned or cleaned in {"-", "#VALUE!", "#N/A"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
