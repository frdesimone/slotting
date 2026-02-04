from __future__ import annotations

from dataclasses import dataclass

from slotting.algorithms.micro.kpi_state.moves import Move
from slotting.algorithms.micro.kpi_state.physical_eval import (
    PhysicalPreviewResult,
    PhysicalTrayState,
)
from slotting.algorithms.micro.kpi_state.state import ApplyResult, FastKpiState


@dataclass(frozen=True)
class HybridPreviewResult:
    is_valid: bool
    delta_global_kpi: float
    deltas_by_subgroup: dict[str, float]
    reasons: list[str]
    physical: PhysicalPreviewResult | None = None


class HybridKpiState:
    def __init__(
        self,
        logical_state: FastKpiState,
        physical_state: PhysicalTrayState,
    ) -> None:
        self._logical = logical_state
        self._physical = physical_state

    @property
    def global_kpi(self) -> float:
        return self._logical.global_kpi

    def subgroup_ids(self) -> list[str]:
        return list(self._logical.subgroups.keys())

    def subgroup_skus(self, subgroup_id: str) -> list[str]:
        return list(self._logical.subgroups[subgroup_id].sku_ids)

    def all_trays(self) -> list:
        return self._physical.all_trays()

    def subgroup_size(self, subgroup_id: str) -> int:
        return len(self._logical.subgroups[subgroup_id].sku_ids)

    def max_subgroup_size(self) -> int:
        return self._logical._config.subgroup_max_size  # type: ignore[attr-defined]

    def preview_move(self, move: Move) -> HybridPreviewResult:
        logical, new_sku_ids = self._logical.preview_move_with_candidates(move)
        if not logical.is_valid:
            return HybridPreviewResult(
                is_valid=False,
                delta_global_kpi=0.0,
                deltas_by_subgroup={},
                reasons=logical.reasons,
                physical=None,
            )
        if new_sku_ids is None:
            return HybridPreviewResult(
                is_valid=False,
                delta_global_kpi=0.0,
                deltas_by_subgroup={},
                reasons=["invalid_move"],
                physical=None,
            )
        physical = self._physical.preview_subgroup_change(new_sku_ids)
        if not physical.is_valid:
            return HybridPreviewResult(
                is_valid=False,
                delta_global_kpi=0.0,
                deltas_by_subgroup={},
                reasons=physical.reasons,
                physical=physical,
            )
        return HybridPreviewResult(
            is_valid=True,
            delta_global_kpi=logical.delta_global_kpi,
            deltas_by_subgroup=logical.deltas_by_subgroup,
            reasons=[],
            physical=physical,
        )

    def apply_move(self, move: Move) -> ApplyResult:
        preview = self.preview_move(move)
        if not preview.is_valid or preview.physical is None:
            return ApplyResult(
                is_valid=False,
                delta_global_kpi=0.0,
                deltas_by_subgroup={},
                reasons=preview.reasons,
                global_kpi=self._logical.global_kpi,
            )
        logical = self._logical.apply_move(move)
        if preview.physical.new_trays_by_subgroup is not None:
            self._physical.apply_subgroup_change(preview.physical.new_trays_by_subgroup)
        return logical
