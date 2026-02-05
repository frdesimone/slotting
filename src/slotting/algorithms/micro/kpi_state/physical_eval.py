from __future__ import annotations

from dataclasses import dataclass

from slotting.algorithms.micro.config import MicroSlottingConfig
from slotting.algorithms.micro.step7.allocation import build_trays_for_subgroup
from slotting.models import SKU, Subgroup, Tray


@dataclass(frozen=True)
class PhysicalPreviewResult:
    is_valid: bool
    reasons: list[str]
    new_trays_by_subgroup: dict[str, list[Tray]] | None = None
    tray_count_before: int = 0
    tray_count_after: int = 0
    area_waste_ratio_before: float = 0.0
    area_waste_ratio_after: float = 0.0


class PhysicalTrayState:
    def __init__(
        self,
        trays: list[Tray],
        subgroups: dict[str, Subgroup],
        sku_by_id: dict[str, SKU],
        config: MicroSlottingConfig,
    ) -> None:
        self._sku_by_id = sku_by_id
        self._config = config
        self._subgroups = subgroups
        self._trays_by_subgroup: dict[str, list[Tray]] = {}
        for tray in trays:
            self._trays_by_subgroup.setdefault(tray.subgroup_id, []).append(tray)

    @property
    def trays_by_subgroup(self) -> dict[str, list[Tray]]:
        return self._trays_by_subgroup

    def all_trays(self) -> list[Tray]:
        return [tray for trays in self._trays_by_subgroup.values() for tray in trays]

    def tray_count(self) -> int:
        return self._total_trays()

    def area_waste_ratio(self) -> float:
        used, capacity = self._area_used_capacity(self.all_trays())
        if capacity <= 0:
            return 0.0
        return max(capacity - used, 0.0) / capacity

    def preview_subgroup_change(
        self, new_sku_ids: dict[str, list[str]]
    ) -> PhysicalPreviewResult:
        reasons: list[str] = []
        new_trays_by_subgroup: dict[str, list[Tray]] = {}
        old_count = 0
        new_count = 0

        for sg_id, sku_ids in new_sku_ids.items():
            trays = self._preview_single_subgroup(sg_id, sku_ids, reasons)
            if trays is None:
                continue
            new_trays_by_subgroup[sg_id] = trays
            old_count += len(self._trays_by_subgroup.get(sg_id, []))
            new_count += len(trays)
            if any(not tray.items for tray in trays):
                reasons.append(f"empty_tray_generated:{sg_id}")

        if self._exceeds_max_trays(old_count, new_count):
            total_after = self._total_trays() - old_count + new_count
            reasons.append(f"max_trays_exceeded:{total_after}>{self._config.max_trays}")
        trays_before = self._total_trays()
        trays_after = trays_before - old_count + new_count
        area_waste_ratio_before = self.area_waste_ratio()
        area_waste_ratio_after = self._preview_area_waste_ratio(new_trays_by_subgroup)

        return PhysicalPreviewResult(
            not reasons,
            reasons,
            new_trays_by_subgroup,
            tray_count_before=trays_before,
            tray_count_after=trays_after,
            area_waste_ratio_before=area_waste_ratio_before,
            area_waste_ratio_after=area_waste_ratio_after,
        )

    def apply_subgroup_change(self, new_trays_by_subgroup: dict[str, list[Tray]]) -> None:
        for sg_id, trays in new_trays_by_subgroup.items():
            self._trays_by_subgroup[sg_id] = trays

    def _total_trays(self) -> int:
        return sum(len(trays) for trays in self._trays_by_subgroup.values())

    def _preview_single_subgroup(
        self,
        sg_id: str,
        sku_ids: list[str],
        reasons: list[str],
    ) -> list[Tray] | None:
        subgroup = self._subgroups.get(sg_id)
        if subgroup is None:
            reasons.append(f"subgroup_not_found:{sg_id}")
            return None
        if not sku_ids:
            reasons.append(f"subgroup_empty:{sg_id}")
            return None
        temp_subgroup = Subgroup(
            subgroup_id=subgroup.subgroup_id,
            group_id=subgroup.group_id,
            sku_ids=list(sku_ids),
            score=subgroup.score,
        )
        return build_trays_for_subgroup(
            temp_subgroup,
            self._sku_by_id,
            self._config,
            max_trays_limit=self._config.max_trays,
        )

    def _exceeds_max_trays(self, old_count: int, new_count: int) -> bool:
        total_after = self._total_trays() - old_count + new_count
        return total_after > self._config.max_trays

    def _preview_area_waste_ratio(
        self,
        new_trays_by_subgroup: dict[str, list[Tray]],
    ) -> float:
        used = 0.0
        capacity = 0.0
        replaced = set(new_trays_by_subgroup.keys())
        for sg_id, trays in self._trays_by_subgroup.items():
            if sg_id in replaced:
                continue
            area_used, area_capacity = self._area_used_capacity(trays)
            used += area_used
            capacity += area_capacity
        for trays in new_trays_by_subgroup.values():
            area_used, area_capacity = self._area_used_capacity(trays)
            used += area_used
            capacity += area_capacity
        if capacity <= 0:
            return 0.0
        return max(capacity - used, 0.0) / capacity

    @staticmethod
    def _area_used_capacity(trays: list[Tray]) -> tuple[float, float]:
        used = 0.0
        capacity = 0.0
        for tray in trays:
            used += tray.area_used
            capacity += tray.max_area
        return used, capacity
