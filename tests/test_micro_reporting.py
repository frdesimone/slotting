from __future__ import annotations

import csv
from pathlib import Path

from slotting.algorithms.micro import MicroSlottingConfig, build_tray_plans
from slotting.algorithms.micro.affinity_graph import build_affinity_graph
from slotting.algorithms.micro.reporting import build_run_report
from slotting.algorithms.micro.step7.csv_export import trays_to_csv_rows
from slotting.models import AffinityGroup, AffinityNeighbor, Order, SKU


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    content = "\n".join(",".join(row) for row in rows)
    path.write_text(content, encoding="utf-8")


def test_reporting_includes_sections() -> None:
    skus = [SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1)]
    orders = [Order(order_id="o1", sku_ids=["A"])]
    groups = [AffinityGroup(seed_sku_id="A", sku_ids=["A"], score=1.0)]
    report = build_run_report(
        skus=skus,
        orders=orders,
        groups=groups,
        selected_groups=groups,
        tray_plans=[],
        stats=type("Stats", (), {"skipped_missing_data": 0, "skipped_zero_rot": 0, "orders_filtered_empty": 0})(),
    )
    joined = "\n".join(report.lines)
    assert "Paso 6" in joined
    assert "Paso 7" in joined


def test_reporting_handles_empty_trays() -> None:
    skus = [SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1)]
    report = build_run_report(
        skus=skus,
        orders=[],
        groups=[],
        selected_groups=[],
        tray_plans=[],
        stats=type("Stats", (), {"skipped_missing_data": 0, "skipped_zero_rot": 0, "orders_filtered_empty": 0})(),
    )
    assert any("Trays: 0" in line for line in report.lines)


def test_reporting_selected_volume_line_present() -> None:
    skus = [SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1)]
    groups = [AffinityGroup(seed_sku_id="A", sku_ids=["A"], score=1.0)]
    report = build_run_report(
        skus=skus,
        orders=[],
        groups=groups,
        selected_groups=groups,
        tray_plans=[],
        stats=type("Stats", (), {"skipped_missing_data": 0, "skipped_zero_rot": 0, "orders_filtered_empty": 0})(),
    )
    assert any("Cycle volume total" in line for line in report.lines)


def test_csv_export_affinity_sum() -> None:
    skus = {
        "A": SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1),
        "B": SKU(sku_id="B", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1),
    }
    affinity_graph = {
        "A": [AffinityNeighbor(sku_id="B", affinity=0.5)],
        "B": [AffinityNeighbor(sku_id="A", affinity=0.5)],
    }
    from slotting.models import Tray, TrayItem

    tray = Tray(
        tray_id="t1",
        group_id="g1",
        subgroup_id="g1-h1",
        height=10.0,
        max_area=100.0,
        max_weight=100.0,
        area_used=10.0,
        weight_used=1.0,
        items=[
            TrayItem(
                sku_id="A",
                units=1.0,
                unit_volume=1e-6,
                unit_weight=1.0,
                total_volume=1e-6,
                total_weight=1.0,
                unit_area=1.0,
                total_area=1.0,
            ),
            TrayItem(
                sku_id="B",
                units=1.0,
                unit_volume=1e-6,
                unit_weight=1.0,
                total_volume=1e-6,
                total_weight=1.0,
                unit_area=1.0,
                total_area=1.0,
            ),
        ],
    )
    rows = trays_to_csv_rows([tray], skus, affinity_graph)
    assert rows[1][11] == "0.500000"


def test_unassigned_include_flag_excludes_unassigned() -> None:
    config = MicroSlottingConfig(unassigned_include=False)
    plans = build_tray_plans(
        selected_groups=[],
        skus=[SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1)],
        affinity_graph={},
        config=config,
    )
    assert plans == []


def test_cli_smoke_outputs_csv(tmp_path: Path, monkeypatch) -> None:
    codes_path = tmp_path / "codes.csv"
    orders_path = tmp_path / "orders.csv"
    trays_path = tmp_path / "trays.csv"

    _write_csv(
        codes_path,
        [
            ["", "Código II", "Promedio VTA", "m3 x unidad", "Peso [kgrs]", "Alto [mm]", "Ancho [mm]", "Largo [mm]"],
            ["", "1", "1", "0.0001", "1.0", "10", "10", "10"],
        ],
    )
    _write_csv(
        orders_path,
        [
            ["Fecha pedido", "Nro pedido", "Código II - Producto", "Cantidad unidades"],
            ["6/13/2025", "A1", "1", "1"],
        ],
    )

    import importlib.util
    from pathlib import Path as _Path

    script_path = _Path(__file__).resolve().parents[1] / "scripts" / "run_micro_slotting.py"
    spec = importlib.util.spec_from_file_location("run_micro_slotting", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    main = module.main

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_micro_slotting.py",
            "--codes-csv",
            str(codes_path),
            "--orders-csv",
            str(orders_path),
            "--trays-csv",
            str(trays_path),
            "--group-seed-count",
            "1",
            "--graph-top-k-neighbors",
            "1",
            "--graph-aff-min",
            "0",
            "--group-max-size",
            "2",
        ],
    )
    assert main() == 0
    assert trays_path.exists()


def test_config_new_names_present() -> None:
    config = MicroSlottingConfig()
    assert config.graph_top_k_neighbors > 0
    assert config.group_seed_count > 0
    assert config.subgroup_size_gamma >= 0
    assert config.unassigned_include in {True, False}


def test_affinity_graph_uses_new_config_names() -> None:
    skus = [
        SKU(sku_id="A", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1),
        SKU(sku_id="B", rot=1, height=10, volume=1e-6, weight=1, cycle_units=1),
    ]
    orders = [Order(order_id="o1", sku_ids=["A", "B"])]
    config = MicroSlottingConfig(
        graph_top_k_neighbors=1,
        graph_aff_min=0.0,
    )
    graph = build_affinity_graph(
        orders=orders,
        top_k=config.graph_top_k_neighbors,
        aff_min=config.graph_aff_min,
        metric=config.affinity_metric,
    )
    assert graph["A"][0].sku_id == "B"
