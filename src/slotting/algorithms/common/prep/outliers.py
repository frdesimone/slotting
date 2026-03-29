"""
Módulo para detección de anomalías (outliers) en datos de entrada de Slotting.
Sistema 100% dinámico basado en reglas configurables.
"""
from __future__ import annotations
from typing import List, Dict, Any

import numpy as np

from slotting.algorithms.common.prep.codes import SkuRecord
from slotting.models.order import Order


def detect_outliers(
    skus: List[SkuRecord],
    orders: List[Order],
    rules: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """
    Escanea SKUs y Pedidos según reglas dinámicas.
    Cada regla: {"id": str, "name": str, "target": "sku"|"order", "attribute": str, "min_val": float, "max_val": float, "enabled": bool}
    Fuera del rango [min_val, max_val] = outlier.
    Para attribute="frequency" (target=sku): se calcula la frecuencia de aparición en pedidos.
    """
    _DEFAULT_RULES = [
        {"id": "heavy", "name": "Pesados", "target": "sku", "attribute": "weight", "min_val": 0, "max_val": 25, "enabled": True},
        {"id": "bulky", "name": "Voluminosos", "target": "sku", "attribute": "volume", "min_val": 0, "max_val": 0.05, "enabled": True},
        {"id": "massive", "name": "Pedidos B2B", "target": "order", "attribute": "lines", "min_val": 0, "max_val": 50, "enabled": True},
        {"id": "ubiquitous", "name": "Omnipresentes", "target": "sku", "attribute": "frequency", "min_val": 0, "max_val": 0.15, "enabled": True},
    ]
    rules = rules if rules else _DEFAULT_RULES
    result: Dict[str, List[Dict[str, Any]]] = {}

    sku_by_id = {s.sku_id: s for s in skus}
    sku_appearances: Dict[str, int] = {}
    for order in orders:
        for sku_id in order.sku_ids:
            sku_appearances[sku_id] = sku_appearances.get(sku_id, 0) + 1
    total_orders = len(orders)
    sku_frequency = {sid: (c / total_orders if total_orders > 0 else 0) for sid, c in sku_appearances.items()}

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if rule.get("enabled", True) is False:
            continue

        rule_id = rule.get("id") or rule.get("name") or "unknown"
        rule_name = rule.get("name") or rule_id
        target = rule.get("target", "sku")
        attribute = rule.get("attribute", "")
        min_val = float(rule.get("min_val", 0))
        max_val = float(rule.get("max_val", float("inf")))
        rule_type = rule.get("rule_type", "absolute")

        items: List[Dict[str, Any]] = []

        if target == "sku":
            if attribute == "frequency":
                freqs = list(sku_frequency.values())
                if rule_type == "percentile" and freqs:
                    lower_bound = np.percentile(freqs, min_val)
                    upper_bound = np.percentile(freqs, max_val)
                else:
                    lower_bound, upper_bound = min_val, max_val
                for sku_id, freq in sku_frequency.items():
                    if freq < lower_bound or freq > upper_bound:
                        sku = sku_by_id.get(sku_id)
                        items.append({
                            "sku_id": sku_id,
                            "description": (getattr(sku, "description", None) or "") if sku else "",
                            "value": freq,
                            "count": sku_appearances.get(sku_id, 0),
                        })
                items.sort(key=lambda x: x["value"], reverse=True)
            else:
                valid_vals = []
                for sku in skus:
                    val = getattr(sku, attribute, None)
                    if val is not None:
                        try:
                            valid_vals.append(float(val))
                        except (TypeError, ValueError):
                            pass

                if rule_type == "percentile" and valid_vals:
                    lower_bound = np.percentile(valid_vals, min_val)
                    upper_bound = np.percentile(valid_vals, max_val)
                else:
                    lower_bound, upper_bound = min_val, max_val

                for sku in skus:
                    val = getattr(sku, attribute, None)
                    if val is None:
                        continue
                    try:
                        v = float(val)
                    except (TypeError, ValueError):
                        continue

                    if v < lower_bound or v > upper_bound:
                        items.append({
                            "sku_id": sku.sku_id,
                            "description": getattr(sku, "description", "") or "",
                            "value": v,
                        })
                # Ordenar por distancia al rango válido: las violaciones más extremas primero,
                # independientemente de si están por encima o por debajo del límite.
                items.sort(
                    key=lambda x: (lower_bound - x["value"]) if x["value"] < lower_bound else (x["value"] - upper_bound),
                    reverse=True,
                )

        elif target == "order":
            attribute = attribute or "lines"
            lines_list = [len(o.sku_ids) for o in orders]
            if rule_type == "percentile" and lines_list:
                lower_bound = np.percentile(lines_list, min_val)
                upper_bound = np.percentile(lines_list, max_val)
            else:
                lower_bound, upper_bound = min_val, max_val

            for order in orders:
                lines = len(order.sku_ids)
                if lines < lower_bound or lines > upper_bound:
                    items.append({
                        "order_id": order.order_id,
                        "description": f"Pedido con {lines} líneas",
                        "value": lines,
                    })
            items.sort(key=lambda x: x["value"], reverse=True)

        result[rule_id] = {"target": target, "name": rule_name, "attribute": attribute, "items": items}

    return result


def export_outliers_to_file(report: Dict[str, Any], out_path: str):
    """Exporta el reporte de anomalías a un archivo de texto (formato legacy)."""
    from pathlib import Path
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("========================================================\n")
        f.write("           REPORTE DE ANOMALÍAS (OUTLIERS)              \n")
        f.write("========================================================\n\n")
        for rule_id, data in report.items():
            items = data.get("items", []) if isinstance(data, dict) else []
            f.write(f"--- {rule_id} ---\n")
            if items:
                for it in items[:100]:
                    if "sku_id" in it:
                        f.write(f"- SKU: {it['sku_id']:<15} | Valor: {it.get('value', 0)}\n")
                    else:
                        f.write(f"- Pedido: {it.get('order_id', '')} | Valor: {it.get('value', 0)}\n")
            else:
                f.write("Ninguno detectado.\n")
            f.write("\n")
    print(f"📄 Reporte de anomalías guardado en: {path}")
