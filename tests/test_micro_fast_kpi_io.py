from __future__ import annotations

import csv
from pathlib import Path

from slotting.algorithms.micro import MicroSlottingConfig, trays_to_csv_rows
from slotting.algorithms.micro.kpi_state.io import (
    build_subgroups_from_trays,
    dump_state_to_json,
    load_state_from_json,
    load_trays_csv,
    load_units_from_trays_csv,
)
from slotting.algorithms.micro.step7.allocation import build_trays_for_subgroup
from slotting.models import SKU, Subgroup, Tray


def _build_fixture() -> tuple[list[Subgroup], list[Tray], dict[str, SKU]]:
    skus = [
        SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=2),
        SKU(sku_id="B", rot=1, height=12, volume=1e-6, weight=1, cycle_units=1),
    ]
    sku_by_id = {sku.sku_id: sku for sku in skus}
    subgroups = [
        Subgroup(subgroup_id="g1-h1", group_id="g1", sku_ids=["A", "B"], score=0.0)
    ]
    config = MicroSlottingConfig(unassigned_include=False)
    trays: list[Tray] = []
    for sg in subgroups:
        trays.extend(build_trays_for_subgroup(sg, sku_by_id, config))
    return subgroups, trays, sku_by_id


def test_trays_csv_roundtrip(tmp_path: Path) -> None:
    subgroups, trays, sku_by_id = _build_fixture()
    rows = trays_to_csv_rows(trays, sku_by_id, affinity_graph={})
    csv_path = tmp_path / "trays.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)

    loaded = load_trays_csv(csv_path, sku_by_id)
    units_by_sku = load_units_from_trays_csv(csv_path)
    assert units_by_sku["A"] > 0
    assert len(loaded) == len(trays)
    assert sum(len(tray.items) for tray in loaded) == sum(len(tray.items) for tray in trays)

    rebuilt_subgroups = build_subgroups_from_trays(loaded)
    assert rebuilt_subgroups[0].sku_ids == subgroups[0].sku_ids


def test_state_json_roundtrip(tmp_path: Path) -> None:
    subgroups, trays, sku_by_id = _build_fixture()
    config = MicroSlottingConfig(unassigned_include=False)
    affinity_graph = {"A": [], "B": []}
    json_path = tmp_path / "state.json"
    dump_state_to_json(json_path, config, sku_by_id, affinity_graph, subgroups, trays)

    loaded_config, loaded_skus, loaded_graph, loaded_subgroups, loaded_trays = load_state_from_json(
        json_path
    )
    assert loaded_config.max_trays == config.max_trays
    assert set(loaded_skus.keys()) == set(sku_by_id.keys())
    assert loaded_graph.keys() == affinity_graph.keys()
    assert loaded_subgroups[0].sku_ids == subgroups[0].sku_ids
    assert len(loaded_trays) == len(trays)
