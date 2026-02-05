from __future__ import annotations

from dataclasses import dataclass, field

from slotting.algorithms.micro.strategies import (
    AffinityMetric,
    AffinityScorer,
    CandidateSelector,
    FullAffinityScorer,
    JaccardMetric,
    OneHopCandidateSelector,
)


@dataclass(frozen=True)
class MicroSlottingConfig:
    cycle_days: float = 7.0
    graph_top_k_neighbors: int = 50
    graph_aff_min: float = 0.03
    affinity_metric: AffinityMetric = field(default_factory=JaccardMetric)
    affinity_scorer: AffinityScorer = field(default_factory=FullAffinityScorer)
    candidate_selector: CandidateSelector = field(
        default_factory=OneHopCandidateSelector
    )
    group_seed_count: int = 500
    group_seed_strategy: str = "stratified_40_40_20"
    selection_cost_mode: str = "none"
    group_min_delta: float = 0.0
    group_max_size: int = 24
    group_score_wa: float = 0.75
    group_score_wr: float = 0.1
    group_score_wh: float = 0.1
    group_height_ref: float = 25.0
    group_height_p: float = 2.0
    subgroup_max_size: int = 14
    subgroup_size_gamma: float = 0.03
    subgroup_size_p: int = 2
    subgroup_height_weight: float = 0.25
    subgroup_height_dispersion_mode: str = "range"
    subgroup_seed_pairs_cap: int = 20
    subgroup_candidate_eval_cap: int = 10
    subgroup_allow_singleton: bool = False
    subgroup_singleton_strategy: str = "min_loss"
    subgroup_min_delta: float = 0.0
    subgroup_marginal_tray_weight: float = 1.0
    subgroup_marginal_area_waste_weight: float = 200.0
    unassigned_height_delta_max: float = 30.0
    unassigned_include: bool = True
    tray_base_area_max: float = 3513700.0
    tray_weight_max: float = 750.0
    tray_op_void: float = 0.10
    max_trays: int = 256
    optimizer_tray_count_weight: float = 0.2
    optimizer_area_waste_weight: float = 200.0

    def __post_init__(self) -> None:
        self._validate_strategy_inputs()
        self._validate_grouping_params()
        self._validate_subgroup_params()
        self._validate_tray_params()

    def _validate_strategy_inputs(self) -> None:
        if not isinstance(self.affinity_metric, AffinityMetric):
            raise ValueError("affinity_metric must be an instance of AffinityMetric")
        if not isinstance(self.affinity_scorer, AffinityScorer):
            raise ValueError("affinity_scorer must be an instance of AffinityScorer")
        if not isinstance(self.candidate_selector, CandidateSelector):
            raise ValueError(
                "candidate_selector must be an instance of CandidateSelector"
            )

    def _validate_grouping_params(self) -> None:
        if self.cycle_days <= 0:
            raise ValueError("cycle_days must be > 0")
        if self.graph_top_k_neighbors <= 0:
            raise ValueError("graph_top_k_neighbors must be > 0")
        if not 0 <= self.graph_aff_min <= 1:
            raise ValueError("graph_aff_min must be between 0 and 1")
        if self.group_seed_count <= 0:
            raise ValueError("group_seed_count must be > 0")
        if self.group_seed_strategy not in {
            "stratified_60_30_10",
            "stratified_40_40_20",
            "coverage",
            "top_rot",
        }:
            raise ValueError(
                "group_seed_strategy must be stratified_60_30_10, stratified_40_40_20, coverage or top_rot"
            )
        if self.selection_cost_mode not in {"none", "cycle_volume"}:
            raise ValueError("selection_cost_mode must be none or cycle_volume")
        if self.group_max_size <= 0:
            raise ValueError("group_max_size must be > 0")
        if self.group_min_delta < 0:
            raise ValueError("group_min_delta must be >= 0")
        if self.group_score_wa < 0 or self.group_score_wr < 0 or self.group_score_wh < 0:
            raise ValueError("group_score_wa/wr/wh must be >= 0")
        if self.group_height_ref <= 0:
            raise ValueError("group_height_ref must be > 0")
        if self.group_height_p <= 0:
            raise ValueError("group_height_p must be > 0")

    def _validate_subgroup_params(self) -> None:
        if self.subgroup_max_size < 2:
            raise ValueError("subgroup_max_size must be >= 2")
        if self.subgroup_size_gamma < 0:
            raise ValueError("subgroup_size_gamma must be >= 0")
        if self.subgroup_size_p < 2:
            raise ValueError("subgroup_size_p must be >= 2")
        if self.subgroup_height_weight < 0:
            raise ValueError("subgroup_height_weight must be >= 0")
        if self.subgroup_height_dispersion_mode != "range":
            raise ValueError("subgroup_height_dispersion_mode must be range")
        if self.subgroup_seed_pairs_cap < 0:
            raise ValueError("subgroup_seed_pairs_cap must be >= 0")
        if self.subgroup_candidate_eval_cap < 0:
            raise ValueError("subgroup_candidate_eval_cap must be >= 0")
        if self.subgroup_singleton_strategy not in {"min_loss", "allow_singleton"}:
            raise ValueError(
                "subgroup_singleton_strategy must be min_loss or allow_singleton"
            )
        if self.subgroup_min_delta < 0:
            raise ValueError("subgroup_min_delta must be >= 0")
        if self.subgroup_marginal_tray_weight < 0:
            raise ValueError("subgroup_marginal_tray_weight must be >= 0")
        if self.subgroup_marginal_area_waste_weight < 0:
            raise ValueError("subgroup_marginal_area_waste_weight must be >= 0")
        if self.unassigned_height_delta_max < 0:
            raise ValueError("unassigned_height_delta_max must be >= 0")

    def _validate_tray_params(self) -> None:
        if self.tray_base_area_max <= 0:
            raise ValueError("tray_base_area_max must be > 0")
        if self.tray_weight_max <= 0:
            raise ValueError("tray_weight_max must be > 0")
        if not 0 <= self.tray_op_void < 1:
            raise ValueError("tray_op_void must be between 0 and 1")
        if self.max_trays <= 0:
            raise ValueError("max_trays must be > 0")
        if self.optimizer_tray_count_weight < 0:
            raise ValueError("optimizer_tray_count_weight must be >= 0")
        if self.optimizer_area_waste_weight < 0:
            raise ValueError("optimizer_area_waste_weight must be >= 0")
