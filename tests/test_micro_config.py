from __future__ import annotations

import pytest

from slotting.algorithms.micro import MicroSlottingConfig


def test_micro_slotting_config_validates_inputs() -> None:
    with pytest.raises(ValueError):
        MicroSlottingConfig(affinity_metric="unknown")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        MicroSlottingConfig(affinity_scorer="unknown")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        MicroSlottingConfig(candidate_selector="unknown")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        MicroSlottingConfig(aff_min=-0.1)
    with pytest.raises(ValueError):
        MicroSlottingConfig(max_group_size=0)
