"""Modelo de configuración de equipos para Macro Slotting."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StorageConfig:
    """Configuración paramétrica de un tipo de almacenamiento."""

    name: str
    num_locations: int
    max_w: float
    max_l: float
    is_variable_height: bool
    max_weight_loc: float
    occupancy_pct: float
    cycle_days: int
    cycle_vol_limit: float
    max_h_loc: float = 0.0
    max_h_storage: float = 0.0
    categories: list[str] = field(default_factory=list)
    priority: int = 99  # Para ordenamiento; 1 = más prioritario
    max_vol_per_sku: float = float("inf")  # Límite volumen por SKU (legacy: max_volume)
    capacity_m3: float = 0.0  # Legacy: capacidad total en m³; si > 0 se usa en vez de num_locations*dims

    def _occupancy_factor(self) -> float:
        """Factor de ocupación (0-1). Soporta occupancy_pct como 0.85 o 85."""
        pct = self.occupancy_pct
        return pct if pct <= 1.0 else pct / 100.0

    def effective_capacity_m3(self) -> float:
        """Capacidad efectiva en m³ para límites de asignación."""
        if self.capacity_m3 > 0:
            return self.capacity_m3 * self._occupancy_factor()
        if self.max_w == float("inf") or self.max_l == float("inf"):
            return float("inf")
        total, _ = self._capacity_and_max_loc_vol()
        return total

    def _capacity_and_max_loc_vol(self) -> tuple[float, float]:
        """Retorna (total_capacity_m3, max_loc_vol) según dimensiones dinámicas."""
        occ = self._occupancy_factor()
        base_area = self.max_w * self.max_l
        if self.max_w == float("inf") or self.max_l == float("inf"):
            return (float("inf"), self.max_vol_per_sku)
        if self.capacity_m3 > 0:
            return (self.capacity_m3 * occ, self.max_vol_per_sku)
        if self.is_variable_height:
            total_capacity_m3 = base_area * (self.max_h_storage or 1.0) * occ
            max_loc_vol = base_area * (self.max_h_storage or 1.0)
        else:
            loc_vol = base_area * (self.max_h_loc if self.max_h_loc > 0 else 1.0)
            total_capacity_m3 = self.num_locations * loc_vol * occ
            max_loc_vol = loc_vol
        return (total_capacity_m3, max_loc_vol)

    def to_dict(self) -> dict[str, Any]:
        """Serializa a dict para persistencia/API."""
        return {
            "name": self.name,
            "num_locations": self.num_locations,
            "max_w": self.max_w,
            "max_l": self.max_l,
            "is_variable_height": self.is_variable_height,
            "max_h_loc": self.max_h_loc,
            "max_h_storage": self.max_h_storage,
            "max_weight_loc": self.max_weight_loc,
            "occupancy_pct": self.occupancy_pct,
            "cycle_days": self.cycle_days,
            "cycle_vol_limit": self.cycle_vol_limit,
            "categories": self.categories,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StorageConfig:
        """Construye StorageConfig desde dict (nuevo o legacy)."""
        if not d or not isinstance(d, dict):
            return cls(
                name="VLM",
                num_locations=100,
                max_w=float("inf"),
                max_l=float("inf"),
                is_variable_height=True,
                max_weight_loc=25.0,
                occupancy_pct=0.85,
                cycle_days=15,
                cycle_vol_limit=999.0,
            )

        # Formato nuevo (paramétrico)
        if "num_locations" in d or "max_w" in d or "max_weight_loc" in d:
            max_vol = float("inf")
            if "max_vol_per_sku" in d:
                max_vol = float(d["max_vol_per_sku"])
            elif d.get("max_h_loc", 0) and d.get("max_w") and d.get("max_l"):
                max_vol = float(d.get("max_w", 1)) * float(d.get("max_l", 1)) * float(d.get("max_h_loc", 1))
            return cls(
                name=str(d.get("name", "VLM")),
                num_locations=int(d.get("num_locations", 100)),
                max_w=float(d.get("max_w", float("inf"))),
                max_l=float(d.get("max_l", float("inf"))),
                is_variable_height=bool(d.get("is_variable_height", True)),
                max_h_loc=float(d.get("max_h_loc", 0.0)),
                max_h_storage=float(d.get("max_h_storage", 0.0)),
                max_weight_loc=float(d.get("max_weight_loc", 25.0)),
                occupancy_pct=float(d.get("occupancy_pct", 0.85)),
                cycle_days=int(d.get("cycle_days", 15)),
                cycle_vol_limit=float(d.get("cycle_vol_limit", 999.0)),
                categories=_parse_categories(d.get("categories", [])),
                priority=int(d.get("priority", 99)),
                max_vol_per_sku=max_vol,
            )

        # Formato legacy (capacity, occupancy, max_volume, etc.)
        allowed = d.get("allowed_categories") or []
        if isinstance(allowed, str):
            allowed = [c.strip() for c in allowed.split(",") if c.strip()]
        elif not isinstance(allowed, list):
            allowed = []

        capacity = float(d.get("capacity", 60.0))
        occupancy = float(d.get("occupancy", 0.85))
        max_vol = float(d.get("max_volume", float("inf")))
        return cls(
            name=str(d.get("name", "VLM")),
            num_locations=100,
            max_w=float("inf"),
            max_l=float("inf"),
            is_variable_height=True,
            max_h_loc=0.0,
            max_h_storage=0.0,
            max_weight_loc=float(d.get("max_weight", 25.0)),
            occupancy_pct=occupancy,
            cycle_days=int(d.get("cycle_days", 15)),
            cycle_vol_limit=float(d.get("max_cycle_volume_limit", 999.0)),
            categories=allowed,
            priority=int(d.get("priority", 99)),
            max_vol_per_sku=max_vol,
            capacity_m3=capacity,
        )


def _parse_categories(raw: Any) -> list[str]:
    """Extrae lista de categorías desde string o lista."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [str(c).strip() for c in raw if c and str(c).strip()]
    if isinstance(raw, str):
        return [c.strip() for c in raw.split(",") if c.strip()]
    return []
