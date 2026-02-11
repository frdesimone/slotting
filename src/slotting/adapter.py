from __future__ import annotations
from typing import Any, Dict, List
from slotting.models import SKU, Order
from slotting.algorithms.macro.config import MacroSlottingConfig
from slotting.algorithms.micro.config import MicroSlottingConfig

def json_to_skus(data: List[Dict[str, Any]]) -> List[SKU]:
    """
    Convierte la lista de SKUs (JSON de Retool) a objetos internos.
    Maneja valores nulos y tipos de datos de forma segura.
    """
    skus = []
    for item in data:
        # Defaults seguros para evitar errores si faltan campos en el JSON
        sku = SKU(
            sku_id=str(item["sku_id"]),
            rot=float(item.get("rot") or 0.0),
            height=float(item.get("height") or 0.0),
            volume=float(item.get("volume") or 0.0),
            weight=float(item.get("weight") or 0.0),
            
            # Campos calculados / opcionales
            cycle_units=float(item.get("cycle_units") or 0.0),
            units_sold_total=float(item.get("units_sold_total") or 0.0),
            
            # Flags de Negocio (Macro)
            is_sensitive=bool(item.get("is_sensitive", False)),
            vlm_eligible=bool(item.get("vlm_eligible", True))
        )
        skus.append(sku)
    return skus

def json_to_orders(data: List[Dict[str, Any]]) -> List[Order]:
    """Convierte el historial de órdenes JSON."""
    return [
        Order(
            order_id=str(o["order_id"]),
            sku_ids=[str(s) for s in o.get("sku_ids", [])]
        )
        for o in data
    ]

def params_to_macro_config(params: Dict[str, Any]) -> MacroSlottingConfig:
    """Convierte parámetros de configuración (headers/body) para Macro."""
    return MacroSlottingConfig(
        vlm_total_usable_volume=float(params.get("vlm_total_volume", 60.0)),
        vlm_occupancy_target=float(params.get("vlm_occupancy", 0.85)),
        # Permite recibir tupla o lista para thresholds
        abc_thresholds=tuple(params.get("abc_thresholds", (0.80, 0.95)))
    )

def params_to_micro_config(params: Dict[str, Any]) -> MicroSlottingConfig:
    """Convierte parámetros de configuración para Micro."""
    # Mapeo directo de claves JSON a atributos de la clase de config
    # Se filtran solo los parámetros que existen en la clase para evitar errores
    valid_keys = MicroSlottingConfig.__dataclass_fields__.keys()
    filtered_params = {k: v for k, v in params.items() if k in valid_keys}
    
    # Instanciamos con lo que vino, el resto usa defaults
    return MicroSlottingConfig(**filtered_params)