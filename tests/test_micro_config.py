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
        MicroSlottingConfig(graph_aff_min=-0.1)
    with pytest.raises(ValueError):
        MicroSlottingConfig(group_max_size=0)
    with pytest.raises(ValueError):
        MicroSlottingConfig(subgroup_max_size=1)
    with pytest.raises(ValueError):
        MicroSlottingConfig(subgroup_height_dispersion_mode="std")
    with pytest.raises(ValueError):
        MicroSlottingConfig(unassigned_height_delta_max=-1.0)
    with pytest.raises(ValueError):
        MicroSlottingConfig(tray_op_void=1.5)
