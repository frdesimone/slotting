from __future__ import annotations

import argparse
from pathlib import Path

from slotting.algorithms.micro import (
    MicroSlottingConfig,
    build_affinity_graph,
    build_groups,
    load_micro_slotting_inputs_with_stats,
    select_groups,
)
from slotting.algorithms.micro.group_score import group_cost_cycle_volume

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
    parser.add_argument("--cycle-days", type=float, default=None)
    parser.add_argument("--period-days", type=float, default=None)
    parser.add_argument("--seed-count", type=int, default=None)
    parser.add_argument("--top-k-neighbors", type=int, default=None)
    parser.add_argument("--aff-min", type=float, default=None)
    parser.add_argument("--min-delta", type=float, default=None)
    parser.add_argument("--max-group-size", type=int, default=None)
    parser.add_argument("--wa", type=float, default=None)
    parser.add_argument("--wr", type=float, default=None)
    parser.add_argument("--wh", type=float, default=None)
    parser.add_argument("--height-ref", type=float, default=None)
    parser.add_argument("--p-height", type=float, default=None)
    parser.add_argument("--include-zero-rot", action="store_true")
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    codes_csv = Path(args.codes_csv)
    orders_csv = Path(args.orders_csv)

    default_config = MicroSlottingConfig()
    cycle_days = (
        default_config.cycle_days if args.cycle_days is None else args.cycle_days
    )
    period_days = 180.0 if args.period_days is None else args.period_days

    skus, orders, stats = load_micro_slotting_inputs_with_stats(
        codes_csv_path=codes_csv,
        orders_csv_path=orders_csv,
        cycle_days=cycle_days,
        period_days=period_days,
        include_zero_rot=args.include_zero_rot,
    )

    config = MicroSlottingConfig(
        cycle_days=cycle_days,
        seed_count=default_config.seed_count
        if args.seed_count is None
        else args.seed_count,
        top_k_neighbors=default_config.top_k_neighbors
        if args.top_k_neighbors is None
        else args.top_k_neighbors,
        aff_min=default_config.aff_min if args.aff_min is None else args.aff_min,
        min_delta=default_config.min_delta if args.min_delta is None else args.min_delta,
        max_group_size=default_config.max_group_size
        if args.max_group_size is None
        else args.max_group_size,
        wa=default_config.wa if args.wa is None else args.wa,
        wr=default_config.wr if args.wr is None else args.wr,
        wh=default_config.wh if args.wh is None else args.wh,
        height_ref=default_config.height_ref
        if args.height_ref is None
        else args.height_ref,
        p_height=default_config.p_height if args.p_height is None else args.p_height,
    )

    affinity_graph = build_affinity_graph(
        orders=orders,
        top_k=config.top_k_neighbors,
        aff_min=config.aff_min,
        metric=config.affinity_metric,
    )
    groups = build_groups(skus=skus, orders=orders, config=config)
    selected_groups = select_groups(groups=groups, skus=skus)

    top_groups = sorted(groups, key=lambda g: g.score, reverse=True)[:5]
    avg_group_size = sum(len(g.sku_ids) for g in groups) / max(len(groups), 1)
    selected_avg_group_size = sum(
        len(g.sku_ids) for g in selected_groups
    ) / max(len(selected_groups), 1)
    selected_top = sorted(selected_groups, key=lambda g: g.score, reverse=True)[:5]
    selected_skus = {sku_id for g in selected_groups for sku_id in g.sku_ids}
    sku_by_id = {sku.sku_id: sku for sku in skus}
    total_cost = sum(
        group_cost_cycle_volume(g.sku_ids, sku_by_id) for g in selected_groups
    )
    selected_details = []
    for group in selected_groups:
        cost = group_cost_cycle_volume(group.sku_ids, sku_by_id)
        density = 1e12 if cost <= 0 else group.score / cost
        rotation = sum(sku_by_id[sku_id].rot for sku_id in group.sku_ids)
        selected_details.append((density, group.score, rotation, cost, group))
    selected_details.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)

    print("Micro-slotting V1")
    print(f"- SKUs: {len(skus)}")
    print(f"- Orders: {len(orders)}")
    print(f"- Groups: {len(groups)} (avg size {avg_group_size:.2f})")
    print(
        f"- Selected groups (Paso 6): {len(selected_groups)} "
        f"(avg size {selected_avg_group_size:.2f}, "
        f"unique SKUs {len(selected_skus)})"
    )
    print(
        f"- Cycle days: {config.cycle_days}, Period days: {period_days}"
    )
    print(f"- Affinity min (effective): {config.aff_min}")
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
    all_affinities = [
        neighbor.affinity
        for neighbors in affinity_graph.values()
        for neighbor in neighbors
    ]
    if all_affinities:
        min_aff = min(all_affinities)
        max_aff = max(all_affinities)
        under_min = sum(1 for a in all_affinities if a < config.aff_min)
        print(
            f"- Affinity graph stats: edges={len(all_affinities)} "
            f"min={min_aff:.4f} max={max_aff:.4f} "
            f"under_aff_min={under_min}"
        )
    else:
        print("- Affinity graph stats: no edges")
    print("Affinity graph (sample):")
    sample_seeds = sorted(skus, key=lambda s: s.rot, reverse=True)[:20]
    for sku in sample_seeds:
        neighbors = affinity_graph.get(sku.sku_id, [])
        if not neighbors:
            print(f"- {sku.sku_id}: (no neighbors)")
            continue
        preview = ", ".join(
            f"{n.sku_id}:{n.affinity:.4f}" for n in neighbors[:10]
        )
        suffix = "..." if len(neighbors) > 10 else ""
        print(f"- {sku.sku_id} -> {preview}{suffix}")
    print("Top selected groups (Paso 6):")
    for group in selected_top:
        sku_preview = ", ".join(group.sku_ids[:5])
        suffix = "..." if len(group.sku_ids) > 5 else ""
        print(
            f"- seed={group.seed_sku_id} size={len(group.sku_ids)} "
            f"score={group.score:.4f} skus=[{sku_preview}{suffix}]"
        )
    print("Selected groups (Paso 6, full detail):")
    for idx, (density, score, rotation, cost, group) in enumerate(selected_details, 1):
        sku_list = ", ".join(group.sku_ids)
        print(
            f"{idx:04d}. seed={group.seed_sku_id} "
            f"size={len(group.sku_ids)} "
            f"score={score:.4f} "
            f"density={density:.6f} "
            f"rotation={rotation:.2f} "
            f"cost={cost:.2f} "
            f"skus=[{sku_list}]"
        )
    print(f"- Selected total cycle volume cost: {total_cost:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
