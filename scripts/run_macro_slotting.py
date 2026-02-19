from __future__ import annotations
import sys
import argparse
import pandas as pd
from pathlib import Path
from rich.console import Console

# --- FIX PYTHONPATH para encontrar 'src' ---
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT / "src"))
# -------------------------------------------

from slotting.algorithms.common.prep import load_slotting_inputs_with_stats
from slotting.algorithms.macro import MacroSlottingConfig, run_macro_slotting
from slotting.visualization import print_kpi_summary, print_macro_results, print_step_header, print_outlier_report
from slotting.algorithms.common.prep.outliers import detect_outliers, export_outliers_to_file

console = Console()

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Macro-Slotting V1.")
    
    # Argumentos de archivos
    parser.add_argument("--codes", required=True, help="Path al archivo de códigos (Excel o CSV)")
    parser.add_argument("--orders", required=True, help="Path al archivo de pedidos (CSV)")
    
    # Output
    parser.add_argument("--out-vlm", default="outputs/macro_vlm_skus.xlsx", help="Archivo de salida con SKUs para VLM")
    
    # Parámetros Macro
    parser.add_argument("--cycle-days", type=float, default=15.0, help="Días de stock objetivo.")
    parser.add_argument("--vlm-volume", type=float, default=60.0, help="Volumen total utilizable VLM (m3).")
    parser.add_argument("--vlm-occupancy", type=float, default=0.85, help="Target ocupación (0-1).")
    
    return parser

def export_vlm_results(results, skus_dict, out_path):
    """
    Exporta los SKUs asignados a VLM en formato Excel Bremen.
    Usa getattr para evitar errores si faltan atributos opcionales.
    """
    print_step_header("Exportando Resultados VLM")
    
    # 1. Filtrar solo los SKUs VLM
    vlm_results = [r for r in results if r.storage_type == "VLM"]
    
    if not vlm_results:
        console.print("[red]⚠️ No hay SKUs asignados a VLM. No se generará archivo.[/red]")
        return

    # 2. Construir DataFrame con columnas formato Bremen
    data = []
    for res in vlm_results:
        sku = skus_dict.get(res.sku_id)
        if not sku: continue
        
        # Usamos getattr con valores por defecto para seguridad
        cycle_vol = getattr(res, 'cycle_volume', 0.0)
        cycle_units = getattr(res, 'cycle_units', 0.0) # Si no existe, pone 0.0
        abc_class = getattr(res, 'abc_class', '')

        row = {
            "Material": sku.sku_id,
            "Clasificación": "", # Vacío para que pase el filtro del Micro loader sin problemas
            "M3/UMB": sku.volume,
            "KG/UMB": sku.weight,
            "KG/Sem BU1": getattr(sku, 'demand_kg_sem', 0.0),
            "Zona Picking": "VLM_MACRO_APPROVED", # Marca de origen para trazabilidad
            
            # Extras informativos (No rompen si faltan)
            "Vol/Cycle": cycle_vol,
            "Units/Cycle": cycle_units,
            "ABC Class": abc_class
        }
        data.append(row)
    
    df = pd.DataFrame(data)
    
    # 3. Guardar Excel
    # Asegurar directorio
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    
    try:
        df.to_excel(out_path, index=False, sheet_name="SLOTTING (trabajado)")
        console.print(f"✅ Exportado: [bold green]{out_path}[/bold green] ({len(df)} SKUs)")
        console.print(f"   -> Archivo listo para alimentar el Micro-Slotting.")
    except Exception as e:
        console.print(f"[red]Error guardando Excel: {e}[/red]")

def main() -> int:
    args = _build_arg_parser().parse_args()
    
    print_step_header(f"Cargando datos (Cobertura: {args.cycle_days} días)")

    # Carga de datos
    # include_zero_rot=True para evaluar todo el maestro
    skus, orders, stats = load_slotting_inputs_with_stats(
        codes_csv_path=args.codes,
        orders_csv_path=args.orders,
        cycle_days=args.cycle_days,
        include_zero_rot=True 
    )
    
    # Manejo robusto: skus puede ser dict o lista según el loader
    skus_list = list(skus.values()) if isinstance(skus, dict) else skus
    
    # Visualización de KPIs de carga
    print_kpi_summary(skus_list, orders, stats)

    outlier_report = detect_outliers(skus, orders)
    print_outlier_report(outlier_report, len(skus), len(orders))
    export_outliers_to_file(outlier_report, "outputs/outliers_report.txt")
    
    # Configuración del Algoritmo Macro
    config = MacroSlottingConfig(
        vlm_total_usable_volume=args.vlm_volume,
        vlm_occupancy_target=args.vlm_occupancy,
        abc_thresholds=(0.80, 0.95)
    )
    
    print_step_header("Ejecutando Macro-Slotting")
    results = run_macro_slotting(skus_list, config)
    
    # Visualización de Resultados en consola
    print_macro_results(results, args.vlm_volume, args.vlm_occupancy)

    # EXPORTAR EXCEL PARA MICRO
    # Preparamos un diccionario para búsqueda rápida por ID
    skus_dict_lookup = skus if isinstance(skus, dict) else {s.sku_id: s for s in skus}
    
    # Llamamos a la exportación
    export_vlm_results(results, skus_dict_lookup, args.out_vlm)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())