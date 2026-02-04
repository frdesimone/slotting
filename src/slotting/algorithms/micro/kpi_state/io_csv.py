from __future__ import annotations

import csv
import json
from pathlib import Path

from slotting.algorithms.micro.prep.codes import load_sku_records_from_codes
from slotting.models import SKU, Subgroup, Tray, TrayItem


def load_rot_from_csv(path: str | Path) -> dict[str, float]:
    rows = list(csv.reader(Path(path).open(encoding="utf-8")))
    if not rows:
        return {}
    header = {name.strip().lower(): idx for idx, name in enumerate(rows[0])}
    if "sku_id" not in header or "rot" not in header:
        raise ValueError("sku_rot.csv must include headers sku_id,rot")
    rot_by_sku: dict[str, float] = {}
    for row in rows[1:]:
        sku_id = row[header["sku_id"]].strip()
        rot = row[header["rot"]].strip()
        if not sku_id or not rot:
            continue
        rot_by_sku[sku_id] = float(rot)
    return rot_by_sku


def load_units_from_trays_csv(path: str | Path) -> dict[str, float]:
    rows = list(csv.reader(Path(path).open(encoding="utf-8")))
    if not rows:
        return {}
    header = {name: idx for idx, name in enumerate(rows[0])}
    if "items_json" not in header:
        raise ValueError("trays.csv missing column: items_json")
    units_by_sku: dict[str, float] = {}
    for row in rows[1:]:
        items_json = row[header["items_json"]]
        items = json.loads(items_json) if items_json else {}
        for sku_id, units in items.items():
            units_by_sku[sku_id] = units_by_sku.get(sku_id, 0.0) + float(units)
    return units_by_sku


def load_skus_from_codes_csv(
    codes_csv_path: str | Path,
    units_by_sku: dict[str, float],
    rot_by_sku: dict[str, float] | None = None,
) -> dict[str, SKU]:
    records = load_sku_records_from_codes(codes_csv_path)
    sku_by_id: dict[str, SKU] = {}
    for sku_id, units in units_by_sku.items():
        record = records.get(sku_id)
        if record is None or record.height is None or record.volume is None or record.weight is None:
            continue
        rot = float(rot_by_sku.get(sku_id, units)) if rot_by_sku is not None else float(units)
        sku_by_id[sku_id] = SKU(
            sku_id=sku_id,
            rot=rot,
            height=record.height,
            volume=record.volume,
            weight=record.weight,
            cycle_units=units,
            avg_units_per_line=record.avg_units_per_line,
        )
    return sku_by_id


def load_trays_csv(path: str | Path, sku_by_id: dict[str, SKU]) -> list[Tray]:
    rows = list(csv.reader(Path(path).open(encoding="utf-8")))
    if not rows:
        return []
    header = {name: idx for idx, name in enumerate(rows[0])}
    required = {
        "tray_id",
        "group_id",
        "subgroup_id",
        "area_used",
        "weight_used",
        "max_height",
        "tray_area_capacity",
        "tray_weight_capacity",
        "items_json",
    }
    missing = required.difference(header.keys())
    if missing:
        raise ValueError(f"trays.csv missing columns: {sorted(missing)}")
    trays: list[Tray] = []
    for row in rows[1:]:
        items_json = row[header["items_json"]]
        items_dict = json.loads(items_json) if items_json else {}
        items: list[TrayItem] = []
        for sku_id, units in items_dict.items():
            sku = sku_by_id.get(sku_id)
            if sku is None:
                raise ValueError(f"SKU {sku_id} missing from codes input")
            unit_area = (sku.volume * 1e9) / max(sku.height, 1e-9)
            total_area = float(units) * unit_area
            total_weight = float(units) * sku.weight
            total_volume = float(units) * sku.volume
            items.append(
                TrayItem(
                    sku_id=sku_id,
                    units=float(units),
                    unit_volume=sku.volume,
                    unit_weight=sku.weight,
                    total_volume=total_volume,
                    total_weight=total_weight,
                    unit_area=unit_area,
                    total_area=total_area,
                )
            )
        trays.append(
            Tray(
                tray_id=row[header["tray_id"]],
                group_id=row[header["group_id"]],
                subgroup_id=row[header["subgroup_id"]],
                height=float(row[header["max_height"]]),
                max_area=float(row[header["tray_area_capacity"]]),
                max_weight=float(row[header["tray_weight_capacity"]]),
                area_used=float(row[header["area_used"]]),
                weight_used=float(row[header["weight_used"]]),
                items=items,
            )
        )
    return trays


def build_subgroups_from_trays(trays: list[Tray], strict: bool = True) -> list[Subgroup]:
    sku_by_subgroup: dict[str, set[str]] = {}
    group_by_subgroup: dict[str, str] = {}
    sku_to_subgroup: dict[str, str] = {}
    for tray in trays:
        group_by_subgroup[tray.subgroup_id] = tray.group_id
        sku_set = sku_by_subgroup.setdefault(tray.subgroup_id, set())
        for item in tray.items:
            if strict and item.sku_id in sku_to_subgroup:
                if sku_to_subgroup[item.sku_id] != tray.subgroup_id:
                    raise ValueError(
                        f"SKU {item.sku_id} appears in multiple subgroups "
                        f"({sku_to_subgroup[item.sku_id]}, {tray.subgroup_id})"
                    )
            sku_to_subgroup[item.sku_id] = tray.subgroup_id
            sku_set.add(item.sku_id)
    subgroups: list[Subgroup] = []
    for subgroup_id, sku_ids in sku_by_subgroup.items():
        subgroups.append(
            Subgroup(
                subgroup_id=subgroup_id,
                group_id=group_by_subgroup.get(subgroup_id, subgroup_id),
                sku_ids=sorted(sku_ids),
                score=0.0,
            )
        )
    return subgroups
