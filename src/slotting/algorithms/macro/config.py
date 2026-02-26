from dataclasses import dataclass, field

@dataclass(frozen=True)
class MacroSlottingConfig:
    # Ahora es una lista dinámica, NO hay variables fijas de VLM
    storage_types: list[dict] = field(default_factory=list)
    abc_thresholds: tuple[float, float] = (0.80, 0.95)