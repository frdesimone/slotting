from __future__ import annotations

import argparse
from pathlib import Path
from collections import Counter

from slotting.algorithms.common.prep.loader import load_slotting_inputs
from slotting.algorithms.macro import MacroSlottingConfig, run_macro_slotting

REPO_ROOT = Path(__file__).resolve().parents[1]

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Macro-Slotting V1.")

    parser.add_argument(
        "--codes-csv",
        default=str(REPO_ROOT / "docs/Base de códigos - semestre jun-nov  (11-1-2026) - Std Logix.xlsx - Base cód. segun pedidos-final.csv"),
        help="Path to master codes CSV."
    )
    parser.add_argument(
        "--orders-csv",
        default=str(REPO_ROOT / "docs/Base de pedidos - semestre jun-nov  (2-1-2026) - Std Logix.xlsx - Consolidado pedidos.csv"),
        help="Path to orders CSV."
    )
    
    # Parámetros Macro
    parser.add_argument("--cycle-days", type=float, default=15.0, help="Días de stock objetivo (cobertura).")
    parser.add_argument("--vlm-volume", type=float, default=60.0, help="Volumen total utilizable de VLMs (m3).")
    parser.add_argument("--vlm-occupancy", type=float, default=0.85, help="Factor de ocupación objetivo (0-1).")
    
    return parser

def main() -> int:
    args = _build_arg_parser().parse_args()
    
    print(f"--- Cargando datos (Cobertura: {args.cycle_days} días) ---")

    skus, _, stats = load_slotting_inputs(
        codes_csv_path=args.codes_csv,
        orders_csv_path=args.orders_csv,
        cycle_days=args.cycle_days,
        include_zero_rot=True # En Macro queremos ver todo el inventario, incluso lo que no rota mucho
    )
    
    print(f"SKUs: {len(skus)}")
    print(f"Stats: {stats}")
    
    # 2. Configurar Macro
    config = MacroSlottingConfig(
        vlm_total_usable_volume=args.vlm_volume,
        vlm_occupancy_target=args.vlm_occupancy,
        abc_thresholds=(0.80, 0.95)
    )
    
    print("\n--- Ejecutando Macro-Slotting ---")
    results = run_macro_slotting(skus, config)
    
    # 3. Reporte de Resultados
    counts = Counter(r.storage_type for r in results)
    vlm_assigned_volume = sum(r.cycle_volume for r in results if r.storage_type == "VLM")
    
    print("\n--- Resultados ---")
    print(f"Distribución por Tipo de Almacenamiento:")
    for store_type, count in counts.items():
        print(f"  {store_type}: {count} SKUs")
        
    print(f"\nUso de VLM:")
    print(f"  Volumen Ocupado: {vlm_assigned_volume:.2f} m3")
    print(f"  Capacidad Objetivo: {args.vlm_volume * args.vlm_occupancy:.2f} m3")
    print(f"  % Llenado (vs Objetivo): {(vlm_assigned_volume / (args.vlm_volume * args.vlm_occupancy)) * 100:.1f}%")
    
    print("\nDetalle ABC en VLM:")
    vlm_abc = Counter(r.abc_class for r in results if r.storage_type == "VLM")
    for cls in sorted(vlm_abc.keys()):
        print(f"  Clase {cls}: {vlm_abc[cls]} SKUs")

    print("\nRazones de rechazo de VLM (Top 5):")
    non_vlm_reasons = Counter(r.reason for r in results if r.storage_type != "VLM")
    for reason, count in non_vlm_reasons.most_common(5):
        print(f"  {reason}: {count}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())