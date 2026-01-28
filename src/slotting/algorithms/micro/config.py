from __future__ import annotations

from dataclasses import dataclass, field

from slotting.algorithms.micro.strategies import (
    AffinityMetric,
    AffinityScorer,
    CandidateSelector,
    JaccardMetric,
    OneHopCandidateSelector,
    StarAffinityScorer,
)


@dataclass(frozen=True)
class MicroSlottingConfig:
    cycle_days: float = 7.0
    top_k_neighbors: int = 30
    aff_min: float = 0.01
    affinity_metric: AffinityMetric = field(default_factory=JaccardMetric)
    affinity_scorer: AffinityScorer = field(default_factory=StarAffinityScorer)
    candidate_selector: CandidateSelector = field(
        default_factory=OneHopCandidateSelector
    )
    seed_count: int = 200
    min_delta: float = 0.0
    max_group_size: int = 12
    wa: float = 0.75
    wr: float = 0.1
    wh: float = 0.15
    height_ref: float = 0.25
    p_height: float = 2.0

    def __post_init__(self) -> None:
        if not isinstance(self.affinity_metric, AffinityMetric):
            raise ValueError("affinity_metric must be an instance of AffinityMetric")
        if not isinstance(self.affinity_scorer, AffinityScorer):
            raise ValueError("affinity_scorer must be an instance of AffinityScorer")
        if not isinstance(self.candidate_selector, CandidateSelector):
            raise ValueError(
                "candidate_selector must be an instance of CandidateSelector"
            )
        if self.cycle_days <= 0:
            raise ValueError("cycle_days must be > 0")
        if self.top_k_neighbors <= 0:
            raise ValueError("top_k_neighbors must be > 0")
        if not 0 <= self.aff_min <= 1:
            raise ValueError("aff_min must be between 0 and 1")
        if self.seed_count <= 0:
            raise ValueError("seed_count must be > 0")
        if self.max_group_size <= 0:
            raise ValueError("max_group_size must be > 0")
        if self.min_delta < 0:
            raise ValueError("min_delta must be >= 0")
        if self.wa < 0 or self.wr < 0 or self.wh < 0:
            raise ValueError("wa/wr/wh must be >= 0")
        if self.height_ref <= 0:
            raise ValueError("height_ref must be > 0")
        if self.p_height <= 0:
            raise ValueError("p_height must be > 0")
