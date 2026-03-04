from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OrderLoadStats:
    total_rows: int = 0
    kept_rows: int = 0
    skipped_missing_fields: int = 0
    skipped_missing_master: int = 0
    total_orders: int = 0
    period_days: float = 180.0


@dataclass
class PrepStats:
    total_skus_master: int = 0
    skipped_zero_rot: int = 0
    skipped_missing_data: int = 0
    total_skus_final: int = 0
    orders_filtered_empty: int = 0
    order_stats: OrderLoadStats | None = None
