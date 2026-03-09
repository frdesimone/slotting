from dataclasses import dataclass, field

from slotting.models.storage import StorageConfig


@dataclass(frozen=True)
class MacroSlottingConfig:
    storage_types: list[StorageConfig] = field(default_factory=list)
    abc_thresholds: tuple[float, float] = (0.80, 0.95)