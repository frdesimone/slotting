from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VLM:
    vlm_id: str
    capacity: float
    load: float = 0.0
