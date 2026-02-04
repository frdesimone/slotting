from __future__ import annotations

from pathlib import Path

from slotting.models import Order, SKU
from .codes import SkuRecord, load_sku_records_from_codes
from .orders import load_orders_from_pedidos
from .stats import PrepStats


def load_micro_slotting_inputs(
    codes_csv_path: str | Path,
    orders_csv_path: str | Path,
    cycle_days: float,
    period_days: float = 180.0,
    include_zero_rot: bool = False,
) -> tuple[list[SKU], list[Order]]:
    """Load SKU + Order inputs from CSV files (prep pipeline)."""
    skus, orders, _ = load_micro_slotting_inputs_with_stats(
        codes_csv_path=codes_csv_path,
        orders_csv_path=orders_csv_path,
        cycle_days=cycle_days,
        period_days=period_days,
        include_zero_rot=include_zero_rot,
    )
    return skus, orders


def load_micro_slotting_inputs_with_stats(
    codes_csv_path: str | Path,
    orders_csv_path: str | Path,
    cycle_days: float,
    period_days: float = 180.0,
    include_zero_rot: bool = False,
) -> tuple[list[SKU], list[Order], PrepStats]:
    """
    Build SKU + Order inputs from the master codes CSV and orders CSV.

    Notes:
    - SKUs missing in the codes file are excluded from orders.
    - SKUs missing height/volume/weight are skipped to keep SKU objects valid.
    - rot is lines per SKU; cycle_units uses summed units scaled by cycle_days/period_days.
    """
    _validate_input_params(cycle_days=cycle_days, period_days=period_days)
    stats = PrepStats()
    sku_records = load_sku_records_from_codes(codes_csv_path)
    stats.total_skus_master = len(sku_records)
    allowed_skus = set(sku_records.keys())
    orders, rot_by_sku, units_by_sku, order_stats = load_orders_from_pedidos(
        orders_csv_path,
        allowed_skus=allowed_skus,
    )
    stats.order_stats = order_stats

    skus = _build_skus(
        sku_records=sku_records,
        rot_by_sku=rot_by_sku,
        units_by_sku=units_by_sku,
        cycle_days=cycle_days,
        period_days=period_days,
        include_zero_rot=include_zero_rot,
        stats=stats,
    )
    filtered_orders = _filter_orders_by_skus(orders, skus, stats)

    return skus, filtered_orders, stats


def _build_skus(
    sku_records: dict[str, SkuRecord],
    rot_by_sku: dict[str, int],
    units_by_sku: dict[str, float],
    cycle_days: float,
    period_days: float,
    include_zero_rot: bool,
    stats: PrepStats,
) -> list[SKU]:
    """Build validated SKU objects with cycle units and rotation."""
    skus: list[SKU] = []
    for sku_id, record in sku_records.items():
        rot = rot_by_sku.get(sku_id, 0)
        if rot <= 0 and not include_zero_rot:
            stats.skipped_zero_rot += 1
            continue
        if record.height is None or record.volume is None or record.weight is None:
            stats.skipped_missing_data += 1
            continue
        cycle_units = _compute_cycle_units(
            units_by_sku=units_by_sku,
            sku_id=sku_id,
            cycle_days=cycle_days,
            period_days=period_days,
        )
        skus.append(
            SKU(
                sku_id=sku_id,
                rot=float(rot),
                height=record.height,
                volume=record.volume,
                weight=record.weight,
                cycle_units=cycle_units,
                avg_units_per_line=record.avg_units_per_line,
            )
        )
    stats.total_skus_final = len(skus)
    return skus


def _compute_cycle_units(
    units_by_sku: dict[str, float],
    sku_id: str,
    cycle_days: float,
    period_days: float,
) -> float:
    units_per_period = units_by_sku.get(sku_id, 0.0)
    return units_per_period * (cycle_days / period_days)


def _filter_orders_by_skus(
    orders: list[Order],
    skus: list[SKU],
    stats: PrepStats,
) -> list[Order]:
    """Remove SKUs missing from master data and drop empty orders."""
    valid_skus = {sku.sku_id for sku in skus}
    filtered_orders: list[Order] = []
    for order in orders:
        sku_ids = [sku_id for sku_id in order.sku_ids if sku_id in valid_skus]
        if not sku_ids:
            stats.orders_filtered_empty += 1
            continue
        filtered_orders.append(Order(order_id=order.order_id, sku_ids=sku_ids))
    return filtered_orders


def _validate_input_params(cycle_days: float, period_days: float) -> None:
    if cycle_days <= 0:
        raise ValueError("cycle_days must be > 0")
    if period_days <= 0:
        raise ValueError("period_days must be > 0")
