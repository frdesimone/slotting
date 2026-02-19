"""
Módulo para detección de anomalías (outliers) en datos de entrada de Slotting.
Ayuda a identificar pedidos o SKUs que pueden distorsionar los cálculos de afinidad o capacidad.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple, Dict

# Corregimos el import para usar SkuRecord desde codes.py
from slotting.algorithms.common.prep.codes import SkuRecord
from slotting.models.order import Order

@dataclass
class OutlierReport:
    # SKUs con problemas físicos
    heavy_skus: List[SkuRecord] = field(default_factory=list)
    bulky_skus: List[SkuRecord] = field(default_factory=list)
    zero_metric_skus: List[SkuRecord] = field(default_factory=list)
    
    # Pedidos anómalos
    massive_orders: List[Order] = field(default_factory=list)
    
    # SKUs que rompen la afinidad (Aparecen en demasiados pedidos)
    ubiquitous_skus: List[Tuple[str, int, float]] = field(default_factory=list) # (sku_id, count, percentage)

def detect_outliers(skus: List[SkuRecord], orders: List[Order]) -> OutlierReport:
    """
    Escanea la lista de SKUs y Pedidos buscando valores atípicos basados en heurísticas de almacén.
    """
    report = OutlierReport()
    
    # 1. Configuración de Umbrales (Ajustables según el cliente)
    MAX_WEIGHT_KG = 25.0      # Más de 25kg por unidad es atípico/peligroso para picking manual
    MAX_VOLUME_M3 = 0.05      # 50 litros (ej. caja de 40x40x30cm) es enorme para un VLM
    MAX_ORDER_LINES = 50      # Pedidos con > 50 líneas distintas suelen ser mayoristas/reposición
    UBIQUITOUS_PCT = 0.15     # Si un SKU está en > 15% de todos los pedidos, suele ser packaging
    
    # --- ANÁLISIS DE SKUs (Física) ---
    for sku in skus:
        vol = getattr(sku, 'volume', 0.0) or 0.0
        weight = getattr(sku, 'weight', 0.0) or 0.0
        
        if vol <= 0 or weight <= 0:
            report.zero_metric_skus.append(sku)
        if weight > MAX_WEIGHT_KG:
            report.heavy_skus.append(sku)
        if vol > MAX_VOLUME_M3:
            report.bulky_skus.append(sku)

    # --- ANÁLISIS DE PEDIDOS (Operativa) ---
    sku_appearances: Dict[str, int] = {}
    
    for order in orders:
        # CORRECCIÓN AQUÍ: usamos order.sku_ids en lugar de order.lines
        lines_count = len(order.sku_ids)
        if lines_count > MAX_ORDER_LINES:
            report.massive_orders.append(order)
            
        # Contar apariciones de SKU para afinidad
        for sku_id in order.sku_ids:
            sku_appearances[sku_id] = sku_appearances.get(sku_id, 0) + 1

    # --- ANÁLISIS DE AFINIDAD (Omnipresencia) ---
    total_orders = len(orders)
    if total_orders > 0:
        for sku_id, count in sku_appearances.items():
            pct = count / total_orders
            if pct >= UBIQUITOUS_PCT:
                report.ubiquitous_skus.append((sku_id, count, pct))
                
    # Ordenar omnipresentes de mayor a menor
    report.ubiquitous_skus.sort(key=lambda x: x[2], reverse=True)
    
    return report


from pathlib import Path

def export_outliers_to_file(report: OutlierReport, out_path: str | Path):
    """
    Exporta el detalle de las anomalías detectadas a un archivo de texto.
    """
    path = Path(out_path)
    # Crear la carpeta si no existe
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with path.open("w", encoding="utf-8") as f:
        f.write("========================================================\n")
        f.write("           REPORTE DE ANOMALÍAS (OUTLIERS)              \n")
        f.write("========================================================\n\n")
        
        f.write("--- 1. SKUs MUY PESADOS (>25kg) ---\n")
        if report.heavy_skus:
            for sku in report.heavy_skus:
                w = getattr(sku, 'weight', 0.0)
                f.write(f"- SKU: {sku.sku_id: <15} | Peso: {w:.2f} kg\n")
        else:
            f.write("Ninguno detectado.\n")
        f.write("\n")
        
        f.write("--- 2. SKUs MUY VOLUMINOSOS (>0.05 m3) ---\n")
        if report.bulky_skus:
            for sku in report.bulky_skus:
                v = getattr(sku, 'volume', 0.0)
                f.write(f"- SKU: {sku.sku_id: <15} | Volumen: {v:.4f} m3\n")
        else:
            f.write("Ninguno detectado.\n")
        f.write("\n")
        
        f.write("--- 3. SKUs CON VOLUMEN/PESO CERO ---\n")
        if report.zero_metric_skus:
            for sku in report.zero_metric_skus:
                v = getattr(sku, 'volume', 0.0)
                w = getattr(sku, 'weight', 0.0)
                f.write(f"- SKU: {sku.sku_id: <15} | Vol: {v:.4f} m3 | Peso: {w:.2f} kg\n")
        else:
            f.write("Ninguno detectado.\n")
        f.write("\n")
        
        f.write("--- 4. PEDIDOS MASIVOS (>50 líneas) ---\n")
        if report.massive_orders:
            # Ordenamos de mayor a menor cantidad de líneas
            sorted_orders = sorted(report.massive_orders, key=lambda o: len(o.sku_ids), reverse=True)
            for order in sorted_orders:
                f.write(f"- Pedido: {order.order_id: <15} | Contiene {len(order.sku_ids)} líneas distintas\n")
        else:
            f.write("Ninguno detectado.\n")
        f.write("\n")
        
        f.write("--- 5. SKUs OMNIPRESENTES (Comodines / Packaging) ---\n")
        if report.ubiquitous_skus:
            for sku_id, count, pct in report.ubiquitous_skus:
                f.write(f"- SKU: {sku_id: <15} | Aparece en {count} pedidos ({pct:.2%} del total)\n")
        else:
            f.write("Ninguno detectado.\n")
            
    print(f"📄 Reporte de anomalías guardado en: {path}")