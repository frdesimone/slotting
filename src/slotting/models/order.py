from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Order:
    order_id: str
    sku_ids: list[str]
