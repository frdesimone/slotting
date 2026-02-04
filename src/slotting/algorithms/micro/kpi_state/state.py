from __future__ import annotations

from dataclasses import dataclass

from slotting.algorithms.micro.config import MicroSlottingConfig
from slotting.algorithms.micro.kpi_state.moves import Move, RelocateMove, SwapMove
from slotting.algorithms.micro.group_score import estimate_cycle_units
from slotting.algorithms.micro.scoring.kpi import logical_group_kpi
from slotting.algorithms.micro.strategies import AffinityGraph
from slotting.models import SKU, Subgroup


@dataclass(frozen=True)
class PreviewResult:
    is_valid: bool
    delta_global_kpi: float
    deltas_by_subgroup: dict[str, float]
    reasons: list[str]


@dataclass(frozen=True)
class ApplyResult:
    is_valid: bool
    delta_global_kpi: float
    deltas_by_subgroup: dict[str, float]
    reasons: list[str]
    global_kpi: float


@dataclass(frozen=True)
class Snapshot:
    subgroup_skus: dict[str, list[str]]
    subgroup_kpis: dict[str, float]
    global_kpi: float
    sku_to_subgroup: dict[str, str]


class FastKpiState:
    def __init__(
        self,
        subgroups: list[Subgroup],
        sku_by_id: dict[str, SKU],
        affinity_graph: AffinityGraph,
        config: MicroSlottingConfig,
    ) -> None:
        self._sku_by_id = sku_by_id
        self._affinity_graph = affinity_graph
        self._config = config
        self._units_by_sku = {
            sku_id: estimate_cycle_units(sku) for sku_id, sku in sku_by_id.items()
        }
        self._subgroups: dict[str, Subgroup] = {sg.subgroup_id: sg for sg in subgroups}
        self._sku_to_subgroup: dict[str, str] = {}
        for sg in subgroups:
            for sku_id in sg.sku_ids:
                if sku_id in self._sku_to_subgroup:
                    raise ValueError(f"SKU {sku_id} appears in multiple subgroups")
                self._sku_to_subgroup[sku_id] = sg.subgroup_id
        self._subgroup_kpis: dict[str, float] = {}
        for sg in subgroups:
            self._subgroup_kpis[sg.subgroup_id] = self._compute_kpi(sg.sku_ids)
        self._global_kpi = sum(self._subgroup_kpis.values())

    @property
    def global_kpi(self) -> float:
        return self._global_kpi

    @property
    def subgroups(self) -> dict[str, Subgroup]:
        return self._subgroups

    def snapshot(self) -> Snapshot:
        subgroup_skus = {sg_id: list(sg.sku_ids) for sg_id, sg in self._subgroups.items()}
        return Snapshot(
            subgroup_skus=subgroup_skus,
            subgroup_kpis=dict(self._subgroup_kpis),
            global_kpi=self._global_kpi,
            sku_to_subgroup=dict(self._sku_to_subgroup),
        )

    def rollback(self, snapshot: Snapshot) -> None:
        for sg_id, sku_ids in snapshot.subgroup_skus.items():
            subgroup = self._subgroups.get(sg_id)
            if subgroup is None:
                continue
            subgroup.sku_ids = list(sku_ids)
        self._subgroup_kpis = dict(snapshot.subgroup_kpis)
        self._global_kpi = snapshot.global_kpi
        self._sku_to_subgroup = dict(snapshot.sku_to_subgroup)

    def preview_move(self, move: Move) -> PreviewResult:
        preview, _ = self._evaluate_move(move, apply=False)
        return preview

    def apply_move(self, move: Move) -> ApplyResult:
        result, _ = self._evaluate_move(move, apply=True)
        return ApplyResult(
            is_valid=result.is_valid,
            delta_global_kpi=result.delta_global_kpi,
            deltas_by_subgroup=result.deltas_by_subgroup,
            reasons=result.reasons,
            global_kpi=self._global_kpi,
        )

    def preview_move_with_candidates(
        self, move: Move
    ) -> tuple[PreviewResult, dict[str, list[str]] | None]:
        return self._evaluate_move(move, apply=False)

    def _evaluate_move(
        self, move: Move, apply: bool
    ) -> tuple[PreviewResult, dict[str, list[str]] | None]:
        reasons: list[str] = []
        if isinstance(move, SwapMove):
            affected_ids, new_sku_ids = self._build_swap_candidate(move, reasons)
        else:
            affected_ids, new_sku_ids = self._build_relocate_candidate(move, reasons)

        if new_sku_ids is None or not self._validate_move(new_sku_ids, reasons):
            return PreviewResult(False, 0.0, {}, reasons), None

        deltas, delta_global = self._compute_deltas(affected_ids, new_sku_ids)

        if apply:
            self._apply_candidate(affected_ids, new_sku_ids, deltas, delta_global)

        return PreviewResult(True, delta_global, deltas, reasons), new_sku_ids

    def candidate_sku_ids(self, move: Move) -> dict[str, list[str]] | None:
        preview, new_sku_ids = self._evaluate_move(move, apply=False)
        if not preview.is_valid:
            return None
        return new_sku_ids

    def _compute_kpi(self, sku_ids: list[str]) -> float:
        return logical_group_kpi(
            sku_ids,
            self._sku_by_id,
            self._affinity_graph,
            self._config,
            self._units_by_sku,
        )

    def _validate_move(
        self, new_sku_ids: dict[str, list[str]], reasons: list[str]
    ) -> bool:
        for sg_id, sku_ids in new_sku_ids.items():
            if not sku_ids:
                reasons.append("subgroup_cannot_be_empty")
                return False
            if len(sku_ids) > self._config.subgroup_max_size:
                reasons.append(f"subgroup_max_size_exceeded:{sg_id}")
                return False
        return True

    def _build_swap_candidate(
        self, move: SwapMove, reasons: list[str]
    ) -> tuple[list[str], dict[str, list[str]] | None]:
        if move.sku_a == move.sku_b:
            reasons.append("swap_skus_must_differ")
        sg_a = self._sku_to_subgroup.get(move.sku_a)
        sg_b = self._sku_to_subgroup.get(move.sku_b)
        if sg_a is None or sg_b is None:
            reasons.append("sku_not_found")
        if sg_a == sg_b:
            reasons.append("swap_requires_distinct_subgroups")
        if reasons:
            return [], None
        new_sku_ids = {
            sg_a: self._swap_sku_list(
                self._subgroups[sg_a].sku_ids, move.sku_a, move.sku_b
            ),
            sg_b: self._swap_sku_list(
                self._subgroups[sg_b].sku_ids, move.sku_b, move.sku_a
            ),
        }
        return [sg_a, sg_b], new_sku_ids

    def _build_relocate_candidate(
        self, move: RelocateMove, reasons: list[str]
    ) -> tuple[list[str], dict[str, list[str]] | None]:
        if move.from_subgroup_id == move.to_subgroup_id:
            reasons.append("relocate_requires_distinct_subgroups")
        actual = self._sku_to_subgroup.get(move.sku_id)
        if actual is None:
            reasons.append("sku_not_found")
        elif actual != move.from_subgroup_id:
            reasons.append("sku_not_in_from_subgroup")
        if move.from_subgroup_id not in self._subgroups:
            reasons.append("from_subgroup_not_found")
        if move.to_subgroup_id not in self._subgroups:
            reasons.append("to_subgroup_not_found")
        if reasons:
            return [], None
        from_ids = [
            sku
            for sku in self._subgroups[move.from_subgroup_id].sku_ids
            if sku != move.sku_id
        ]
        from_ids.sort()
        to_ids = sorted(self._subgroups[move.to_subgroup_id].sku_ids + [move.sku_id])
        return [move.from_subgroup_id, move.to_subgroup_id], {
            move.from_subgroup_id: from_ids,
            move.to_subgroup_id: to_ids,
        }

    def _compute_deltas(
        self,
        affected_ids: list[str],
        new_sku_ids: dict[str, list[str]],
    ) -> tuple[dict[str, float], float]:
        deltas: dict[str, float] = {}
        delta_global = 0.0
        for sg_id in affected_ids:
            current_kpi = self._subgroup_kpis[sg_id]
            candidate_kpi = self._compute_kpi(new_sku_ids[sg_id])
            delta = candidate_kpi - current_kpi
            deltas[sg_id] = delta
            delta_global += delta
        return deltas, delta_global

    def _apply_candidate(
        self,
        affected_ids: list[str],
        new_sku_ids: dict[str, list[str]],
        deltas: dict[str, float],
        delta_global: float,
    ) -> None:
        for sg_id in affected_ids:
            self._subgroups[sg_id].sku_ids = list(new_sku_ids[sg_id])
            self._subgroup_kpis[sg_id] = self._subgroup_kpis[sg_id] + deltas[sg_id]
            self._subgroups[sg_id].score = self._subgroup_kpis[sg_id]
        self._global_kpi += delta_global
        self._reindex_skus(affected_ids)

    @staticmethod
    def _swap_sku_list(sku_ids: list[str], remove_id: str, add_id: str) -> list[str]:
        updated = [sku for sku in sku_ids if sku != remove_id]
        updated.append(add_id)
        updated.sort()
        return updated

    def _reindex_skus(self, subgroup_ids: list[str]) -> None:
        for sg_id in subgroup_ids:
            for sku_id in self._subgroups[sg_id].sku_ids:
                self._sku_to_subgroup[sku_id] = sg_id
