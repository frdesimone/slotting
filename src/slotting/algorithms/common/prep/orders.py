from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from slotting.models import Order
from .parsing import find_header, parse_cell, parse_float, parse_sku_id, read_csv_rows
from .stats import OrderLoadStats


def load_orders_from_pedidos(
    path: str | Path,
    allowed_skus: set[str] | None = None,
) -> tuple[list[Order], dict[str, int], dict[str, float], OrderLoadStats]:
    rows = read_csv_rows(path)
    stats = OrderLoadStats()
    header_map, data_rows = find_header(
        rows,
        required_headers={
            "nro pedido",
            "codigo ii - producto",
            "cantidad unidades",
        },
        source=str(path),
    )

    order_items: dict[str, set[str]] = defaultdict(set)
    rot_by_sku: dict[str, int] = defaultdict(int)
    units_by_sku: dict[str, float] = defaultdict(float)
    for row in data_rows:
        stats.total_rows += 1
        order_id = parse_cell(row[header_map["nro pedido"]])
        sku_id = parse_sku_id(row[header_map["codigo ii - producto"]])
        if not order_id or not sku_id:
            stats.skipped_missing_fields += 1
            continue
        if allowed_skus is not None and sku_id not in allowed_skus:
            stats.skipped_missing_master += 1
            continue
        units = parse_float(row[header_map["cantidad unidades"]]) or 0.0
        order_items[order_id].add(sku_id)
        rot_by_sku[sku_id] += 1
        units_by_sku[sku_id] += units
        stats.kept_rows += 1

    orders = [
        Order(order_id=order_id, sku_ids=sorted(sku_ids))
        for order_id, sku_ids in order_items.items()
    ]
    stats.total_orders = len(orders)

    return orders, rot_by_sku, units_by_sku, stats
