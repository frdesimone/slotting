from __future__ import annotations

from pathlib import Path

import pytest

from slotting.algorithms.micro.prep import load_micro_slotting_inputs_with_stats


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    content = "\n".join(",".join(row) for row in rows)
    path.write_text(content, encoding="utf-8")


def test_load_micro_slotting_inputs_combines_and_filters(tmp_path: Path) -> None:
    codes_path = tmp_path / "codes.csv"
    orders_path = tmp_path / "orders.csv"

    _write_csv(
        codes_path,
        [
            ["", "", ""],
            ["", "CODIGOS INVOLUCRADOS EN PEDIDOS JUNIO NOVIEMBRE", ""],
            ["", "Código II", "Promedio VTA", "m3 x unidad", "Peso [kgrs]", "Alto [mm]", "Ancho [mm]", "Largo [mm]"],
            ["", "6", "2", "-", "-", "10", "20", "30"],
            ["", "6", "2", "0.0005", "1.5", "-", "-", "-"],
            ["", "100", "4", "-", "2.0", "50", "40", "30"],
        ],
    )

    _write_csv(
        orders_path,
        [
            ["Detalle de pedidos", ""],
            ["Fecha pedido", "Nro pedido", "Código II - Producto", "Cantidad unidades"],
            ["6/13/2025", "A1", "6", "1"],
            ["6/13/2025", "A1", "6", "2"],
            ["6/13/2025", "A1", "999", "1"],
            ["6/13/2025", "A2", "100", "1"],
            ["6/13/2025", "A3", "999", "1"],
        ],
    )

    skus, orders, stats = load_micro_slotting_inputs_with_stats(
        codes_path,
        orders_path,
        cycle_days=10,
        period_days=20,
    )

    sku_by_id = {sku.sku_id: sku for sku in skus}
    assert sku_by_id["6"].rot == 2
    assert sku_by_id["6"].weight == pytest.approx(1.5)
    assert sku_by_id["6"].volume == pytest.approx(0.0005)
    assert sku_by_id["100"].volume == pytest.approx(0.05 * 0.04 * 0.03)
    assert sku_by_id["6"].cycle_units == pytest.approx((1 + 2) * (10 / 20))

    order_by_id = {order.order_id: order for order in orders}
    assert order_by_id["A1"].sku_ids == ["6"]
    assert order_by_id["A2"].sku_ids == ["100"]
    assert "A3" not in order_by_id
    assert stats.order_stats is not None
    assert stats.order_stats.skipped_missing_master == 2
