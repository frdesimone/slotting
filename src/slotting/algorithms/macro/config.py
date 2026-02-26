from dataclasses import dataclass, field

@dataclass(frozen=True)
class MacroSlottingConfig:
    # Capacidad Total de los VLMs (en m3)
    # Ejemplo: 4 VLMs * 15 m3 c/u = 60 m3
    vlm_total_usable_volume: float
    
    # Factor de ocupación operativa (ej: 0.85 para dejar 15% de aire)
    vlm_occupancy_target: float = 0.85
    
    # Umbrales acumulados para A y B (C es el resto)
    # (0.80, 0.95) significa: A=0-80%, B=80-95%, C=95-100% del volumen de ventas
    storage_types: list[dict] = field(default_factory=list)
    abc_thresholds: tuple[float, float] = (0.80, 0.95)