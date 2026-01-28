from __future__ import annotations

import argparse
from pathlib import Path

from slotting.algorithms.micro import (
    MicroSlottingConfig,
    build_groups,
    load_micro_slotting_inputs_with_stats,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run micro-slotting V1 from CSV inputs.",
    )
    parser.add_argument(
        "--codes-csv",
        default=str(
            REPO_ROOT
            / "docs/Base de códigos - semestre jun-nov  (11-1-2026) - Std Logix.xlsx - Base cód. segun pedidos-final.csv"
        ),
        help="Path to master codes CSV.",
    )
    parser.add_argument(
        "--orders-csv",
        default=str(
            REPO_ROOT
            / "docs/Base de pedidos - semestre jun-nov  (2-1-2026) - Std Logix.xlsx - Consolidado pedidos.csv"
        ),
        help="Path to orders CSV.",
    )
    parser.add_argument("--cycle-days", type=float, default=7.0)
    parser.add_argument("--period-days", type=float, default=180.0)
    parser.add_argument("--seed-count", type=int, default=200)
    parser.add_argument("--top-k-neighbors", type=int, default=30)
    parser.add_argument("--aff-min", type=float, default=0.01)
    parser.add_argument("--min-delta", type=float, default=0.0)
    parser.add_argument("--max-group-size", type=int, default=12)
    parser.add_argument("--wa", type=float, default=1.0)
    parser.add_argument("--wr", type=float, default=1.0)
    parser.add_argument("--wh", type=float, default=1.0)
    parser.add_argument("--height-ref", type=float, default=0.25)
    parser.add_argument("--p-height", type=float, default=2.0)
    parser.add_argument("--include-zero-rot", action="store_true")
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    codes_csv = Path(args.codes_csv)
    orders_csv = Path(args.orders_csv)

    skus, orders, stats = load_micro_slotting_inputs_with_stats(
        codes_csv_path=codes_csv,
        orders_csv_path=orders_csv,
        cycle_days=args.cycle_days,
        period_days=args.period_days,
        include_zero_rot=args.include_zero_rot,
    )

    config = MicroSlottingConfig(
        cycle_days=args.cycle_days,
        seed_count=args.seed_count,
        top_k_neighbors=args.top_k_neighbors,
        aff_min=args.aff_min,
        min_delta=args.min_delta,
        max_group_size=args.max_group_size,
        wa=args.wa,
        wr=args.wr,
        wh=args.wh,
        height_ref=args.height_ref,
        p_height=args.p_height,
    )

    groups = build_groups(skus=skus, orders=orders, config=config)

    top_groups = sorted(groups, key=lambda g: g.score, reverse=True)[:5]
    avg_group_size = sum(len(g.sku_ids) for g in groups) / max(len(groups), 1)

    print("Micro-slotting V1")
    print(f"- SKUs: {len(skus)}")
    print(f"- Orders: {len(orders)}")
    print(f"- Groups: {len(groups)} (avg size {avg_group_size:.2f})")
    print(
        f"- Cycle days: {config.cycle_days}, Period days: {args.period_days}"
    )
    print(
        f"- Affinity: {type(config.affinity_metric).__name__}, "
        f"Scorer: {type(config.affinity_scorer).__name__}, "
        f"Candidates: {type(config.candidate_selector).__name__}"
    )
    if stats.order_stats is not None:
        print(
            f"- Orders kept: {stats.order_stats.total_orders} "
            f"(lines kept {stats.order_stats.kept_rows}, "
            f"skipped missing fields {stats.order_stats.skipped_missing_fields}, "
            f"skipped missing master {stats.order_stats.skipped_missing_master})"
        )
    print(
        f"- SKUs excluded: missing data {stats.skipped_missing_data}, "
        f"zero rot {stats.skipped_zero_rot}"
    )
    print(f"- Orders filtered empty: {stats.orders_filtered_empty}")
    print("Top groups:")
    for group in top_groups:
        sku_preview = ", ".join(group.sku_ids[:5])
        suffix = "..." if len(group.sku_ids) > 5 else ""
        print(
            f"- seed={group.seed_sku_id} size={len(group.sku_ids)} "
            f"score={group.score:.4f} skus=[{sku_preview}{suffix}]"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
