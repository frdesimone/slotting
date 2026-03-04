from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DataValidation:
    found_columns: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)
    sample_data: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class OrderLoadStats:
    total_rows: int = 0
    kept_rows: int = 0
    skipped_missing_fields: int = 0
    skipped_missing_master: int = 0
    total_orders: int = 0
    period_days: float = 180.0
    maestro_validation: DataValidation | None = None
    pedidos_validation: DataValidation | None = None


@dataclass
class PrepStats:
    total_skus_master: int = 0
    skipped_zero_rot: int = 0
    skipped_missing_data: int = 0
    total_skus_final: int = 0
    orders_filtered_empty: int = 0
    order_stats: OrderLoadStats | None = None
    maestro_validation: DataValidation | None = None
    pedidos_validation: DataValidation | None = None
