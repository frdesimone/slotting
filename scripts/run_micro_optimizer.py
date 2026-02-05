from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from slotting.algorithms.micro import (
    MicroSlottingConfig,
    build_affinity_graph,
    build_groups,
    load_micro_slotting_inputs_with_stats,
    select_groups,
    build_tray_plans,
    trays_to_csv_rows,
)
from slotting.algorithms.micro.kpi_state import (
    build_hybrid_kpi_state,
    build_subgroups_from_trays,
    dump_state_to_json,
    load_affinity_graph_json,
    load_rot_from_csv,
    load_skus_from_codes_csv,
    load_state_from_json,
    load_trays_csv,
    load_units_from_trays_csv,
)
from slotting.algorithms.micro.kpi_state.moves import RelocateMove, SwapMove
from slotting.algorithms.micro.optimization import LocalSearchConfig, OptimizationResult, optimize

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OPT_TRAYS_CSV = REPO_ROOT / "outputs" / "trays_optimized.csv"
DEFAULT_OPT_LOG = REPO_ROOT / "outputs" / "optimizer.log"
DEFAULT_OPT_TRACE = REPO_ROOT / "outputs" / "optimizer_trace.csv"
DEFAULT_OPT_REPORT = REPO_ROOT / "outputs" / "optimizer_report.txt"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run micro-slotting optimizer with configurable flags.",
    )
    io_group = parser.add_argument_group("Inputs")
    group_group = parser.add_argument_group("Grouping")
    subgroup_group = parser.add_argument_group("Subgrouping")
    unassigned_group = parser.add_argument_group("Unassigned")
    tray_group = parser.add_argument_group("Trays")
    optimize_group = parser.add_argument_group("Optimizer")

    io_group.add_argument("--input-mode", choices=["pipeline", "trays", "state-json"], default="trays")
    io_group.add_argument(
        "--codes-csv",
        default=str(
            REPO_ROOT
            / "docs/Base de códigos - semestre jun-nov  (11-1-2026) - Std Logix.xlsx - Base cód. segun pedidos-final.csv"
        ),
        help="Path to master codes CSV.",
    )
    io_group.add_argument(
        "--orders-csv",
        default=str(
            REPO_ROOT
            / "docs/Base de pedidos - semestre jun-nov  (2-1-2026) - Std Logix.xlsx - Consolidado pedidos.csv"
        ),
        help="Path to orders CSV.",
    )
    io_group.add_argument("--input-trays-csv", type=str, default=str(REPO_ROOT / "outputs" / "trays.csv"))
    io_group.add_argument(
        "--affinity-graph-json", type=str, default=str(REPO_ROOT / "outputs" / "affinity_graph.json")
    )
    io_group.add_argument("--sku-rot-csv", type=str, default=None)
    io_group.add_argument("--state-json", type=str, default=None)
    io_group.add_argument("--state-out-json", type=str, default=None)
    io_group.add_argument("--moves-json", type=str, default=None)
    io_group.add_argument("--apply-only", action="store_true")
    io_group.add_argument("--cycle-days", type=float, default=None)
    io_group.add_argument("--period-days", type=float, default=None)
    io_group.add_argument("--include-zero-rot", action="store_true")

    group_group.add_argument("--group-seed-count", type=int, default=None)
    group_group.add_argument(
        "--group-seed-strategy",
        type=str,
        choices=["stratified_60_30_10", "stratified_40_40_20", "coverage", "top_rot"],
        default=None,
    )
    group_group.add_argument(
        "--selection-cost-mode",
        type=str,
        choices=["none", "cycle_volume"],
        default=None,
    )
    group_group.add_argument("--graph-top-k-neighbors", type=int, default=None)
    group_group.add_argument("--graph-aff-min", type=float, default=None)
    group_group.add_argument("--group-min-delta", type=float, default=None)
    group_group.add_argument("--group-max-size", type=int, default=None)
    group_group.add_argument("--group-score-wa", type=float, default=None)
    group_group.add_argument("--group-score-wr", type=float, default=None)
    group_group.add_argument("--group-score-wh", type=float, default=None)
    group_group.add_argument("--group-height-ref", type=float, default=None)
    group_group.add_argument("--group-height-p", type=float, default=None)

    subgroup_group.add_argument("--subgroup-max-size", type=int, default=None)
    subgroup_group.add_argument("--subgroup-size-gamma", type=float, default=None)
    subgroup_group.add_argument("--subgroup-size-p", type=int, default=None)
    subgroup_group.add_argument("--subgroup-height-weight", type=float, default=None)
    subgroup_group.add_argument("--subgroup-seed-pairs-cap", type=int, default=None)
    subgroup_group.add_argument("--subgroup-candidate-eval-cap", type=int, default=None)
    subgroup_group.add_argument("--subgroup-min-delta", type=float, default=None)
    subgroup_group.add_argument("--subgroup-marginal-tray-weight", type=float, default=None)
    subgroup_group.add_argument("--subgroup-marginal-area-waste-weight", type=float, default=None)
    subgroup_group.add_argument("--subgroup-allow-singleton", action="store_true")
    subgroup_group.add_argument("--subgroup-singleton-strategy", type=str, default=None)

    unassigned_group.add_argument("--unassigned-height-delta-max", type=float, default=None)
    unassigned_group.add_argument(
        "--unassigned-include",
        dest="unassigned_include",
        action="store_true",
    )
    unassigned_group.add_argument(
        "--no-unassigned-include",
        dest="unassigned_include",
        action="store_false",
    )
    parser.set_defaults(unassigned_include=None)

    tray_group.add_argument("--tray-base-area-max", type=float, default=None)
    tray_group.add_argument("--tray-weight-max", type=float, default=None)
    tray_group.add_argument("--tray-op-void", type=float, default=None)
    tray_group.add_argument("--max-trays", type=int, default=None)

    optimize_group.add_argument("--optimizer-tray-count-weight", type=float, default=None)
    optimize_group.add_argument("--optimizer-area-waste-weight", type=float, default=None)
    optimize_group.add_argument("--opt-iterations", type=int, default=10_000)
    optimize_group.add_argument("--opt-time-budget-ms", type=int, default=None)
    optimize_group.add_argument("--opt-seed", type=int, default=0)
    optimize_group.add_argument("--opt-anneal", action="store_true")
    optimize_group.add_argument("--opt-temp-start", type=float, default=1.0)
    optimize_group.add_argument("--opt-temp-end", type=float, default=0.01)
    optimize_group.add_argument("--opt-log-every", type=int, default=500)
    optimize_group.add_argument("--opt-log-path", type=str, default=str(DEFAULT_OPT_LOG))
    optimize_group.add_argument("--opt-trace-path", type=str, default=str(DEFAULT_OPT_TRACE))
    optimize_group.add_argument("--opt-trays-csv", type=str, default=str(DEFAULT_OPT_TRAYS_CSV))
    optimize_group.add_argument("--opt-report-path", type=str, default=str(DEFAULT_OPT_REPORT))
    optimize_group.add_argument(
        "--opt-report-breakdown",
        action="store_true",
        help="Include per-tray KPI breakdown in the optimizer report.",
    )

    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    codes_csv = Path(args.codes_csv)
    orders_csv = Path(args.orders_csv)

    default_config = MicroSlottingConfig()
    cycle_days = default_config.cycle_days if args.cycle_days is None else args.cycle_days
    period_days = 180.0 if args.period_days is None else args.period_days

    if args.input_mode == "pipeline":
        skus, orders, _ = load_micro_slotting_inputs_with_stats(
            codes_csv_path=codes_csv,
            orders_csv_path=orders_csv,
            cycle_days=cycle_days,
            period_days=period_days,
            include_zero_rot=args.include_zero_rot,
        )
    else:
        skus = []
        orders = []

    config = _build_config(args, default_config, cycle_days)

    if args.input_mode == "pipeline":
        affinity_graph = build_affinity_graph(
            orders=orders,
            top_k=config.graph_top_k_neighbors,
            aff_min=config.graph_aff_min,
            metric=config.affinity_metric,
        )
        groups = build_groups(skus=skus, orders=orders, config=config)
        selected_groups = select_groups(
            groups=groups,
            skus=skus,
            selection_cost_mode=config.selection_cost_mode,
        )
        tray_plans = build_tray_plans(
            selected_groups=selected_groups,
            skus=skus,
            affinity_graph=affinity_graph,
            config=config,
        )
        all_trays = [tray for plan in tray_plans for tray in plan.trays]
        subgroup_lookup = {sg.subgroup_id: sg for plan in tray_plans for sg in plan.subgroups}
        subgroups = list(subgroup_lookup.values())
        sku_by_id = {sku.sku_id: sku for sku in skus}
    elif args.input_mode == "trays":
        if not args.input_trays_csv or not args.affinity_graph_json:
            raise ValueError("trays mode requires --input-trays-csv and --affinity-graph-json")
        affinity_graph = load_affinity_graph_json(args.affinity_graph_json)
        raw_units_by_sku = load_units_from_trays_csv(args.input_trays_csv)
        rot_by_sku = load_rot_from_csv(args.sku_rot_csv) if args.sku_rot_csv else None
        sku_by_id = load_skus_from_codes_csv(codes_csv, raw_units_by_sku, rot_by_sku)
        all_trays = load_trays_csv(args.input_trays_csv, sku_by_id)
        subgroups = build_subgroups_from_trays(all_trays)
    else:
        if not args.state_json:
            raise ValueError("state-json mode requires --state-json")
        config, sku_by_id, affinity_graph, subgroups, all_trays = load_state_from_json(
            args.state_json
        )

    hybrid = build_hybrid_kpi_state(
        subgroups=subgroups,
        trays=all_trays,
        sku_by_id=sku_by_id,
        affinity_graph=affinity_graph,
        config=config,
    )
    if args.moves_json:
        _apply_moves_from_json(hybrid, args.moves_json)
        if args.state_out_json:
            dump_state_to_json(args.state_out_json, config, sku_by_id, affinity_graph, subgroups, hybrid.all_trays())
        if args.apply_only:
            return 0
    opt_config = LocalSearchConfig(
        iterations=args.opt_iterations,
        time_budget_ms=args.opt_time_budget_ms,
        seed=args.opt_seed,
        allow_annealing=args.opt_anneal,
        temp_start=args.opt_temp_start,
        temp_end=args.opt_temp_end,
        log_every=args.opt_log_every,
        log_path=args.opt_log_path,
        trace_path=args.opt_trace_path,
    )
    result = optimize(hybrid, opt_config)
    _validate_units_preserved(all_trays, hybrid.all_trays())
    print(
        f"- Optimization: initial={result.initial_kpi:.6f} "
        f"best={result.best_kpi:.6f} final={result.final_kpi:.6f}"
    )
    _write_optimizer_report(
        path=Path(args.opt_report_path),
        result=result,
        trays_before=all_trays,
        trays_after=hybrid.all_trays(),
        sku_by_id=sku_by_id,
        affinity_graph=affinity_graph,
        config=config,
        include_breakdown=args.opt_report_breakdown,
    )

    opt_csv_path = Path(args.opt_trays_csv)
    opt_csv_path.parent.mkdir(parents=True, exist_ok=True)
    rows = trays_to_csv_rows(hybrid.all_trays(), sku_by_id, affinity_graph)
    with opt_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)
    print(f"- Optimized tray CSV written: {opt_csv_path}")

    return 0


def _apply_moves_from_json(hybrid, path: str) -> None:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    moves = payload if isinstance(payload, list) else payload.get("moves", [])
    for move in moves:
        if move.get("type") == "swap":
            sku_a = move["sku_a"]
            sku_b = move["sku_b"]
            swap = SwapMove(sku_a=sku_a, sku_b=sku_b)
            preview = hybrid.preview_move(swap)
            if not preview.is_valid:
                raise ValueError(f"Invalid swap move: {preview.reasons}")
            hybrid.apply_move(swap)
        elif move.get("type") == "relocate":
            relocate = RelocateMove(
                sku_id=move["sku_id"],
                from_subgroup_id=move["from_subgroup_id"],
                to_subgroup_id=move["to_subgroup_id"],
            )
            preview = hybrid.preview_move(relocate)
            if not preview.is_valid:
                raise ValueError(f"Invalid relocate move: {preview.reasons}")
            hybrid.apply_move(relocate)
        else:
            raise ValueError(f"Unknown move type: {move}")


def _write_optimizer_report(
    path: Path,
    result: OptimizationResult,
    trays_before: list,
    trays_after: list,
    sku_by_id: dict,
    affinity_graph,
    config: MicroSlottingConfig,
    include_breakdown: bool,
) -> None:
    before_stats = _tray_stats(trays_before)
    after_stats = _tray_stats(trays_after)
    before_aff_zero = _affinity_zero_ratio(trays_before, affinity_graph)
    after_aff_zero = _affinity_zero_ratio(trays_after, affinity_graph)
    lines = [
        "Optimizer report",
        f"- Initial KPI: {result.initial_kpi:.6f}",
        f"- Best KPI: {result.best_kpi:.6f}",
        f"- Final KPI: {result.final_kpi:.6f}",
        f"- Iterations: {result.iterations}",
        f"- Accepts: {result.accepts} | Rejects: {result.rejects}",
        "",
        "Trays (before -> after):",
        f"- Count: {before_stats['count']} -> {after_stats['count']}",
        f"- Area used: {before_stats['area_used']:.2f} -> {after_stats['area_used']:.2f}",
        f"- Weight used: {before_stats['weight_used']:.2f} -> {after_stats['weight_used']:.2f}",
        f"- Max height avg: {before_stats['avg_height']:.2f} -> {after_stats['avg_height']:.2f}",
        f"- Zero-affinity trays: {before_aff_zero:.1f}% -> {after_aff_zero:.1f}%",
    ]
    if include_breakdown:
        lines.extend(
            [
                "",
                "Tray KPI breakdown (before, tray-level projection):",
                "tray_id,kpi,affinity,height_penalty,size_penalty,height_diff,sku_count",
            ]
        )
        lines.extend(_tray_kpi_lines(trays_before, sku_by_id, affinity_graph, config))
        lines.extend(
            [
                "",
                "Tray KPI breakdown (after, tray-level projection):",
                "tray_id,kpi,affinity,height_penalty,size_penalty,height_diff,sku_count",
            ]
        )
        lines.extend(_tray_kpi_lines(trays_after, sku_by_id, affinity_graph, config))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"- Optimizer report written: {path}")


def _tray_stats(trays: list) -> dict[str, float]:
    if not trays:
        return {"count": 0, "area_used": 0.0, "weight_used": 0.0, "avg_height": 0.0}
    area_used = sum(tray.area_used for tray in trays)
    weight_used = sum(tray.weight_used for tray in trays)
    avg_height = sum(tray.height for tray in trays) / len(trays)
    return {
        "count": len(trays),
        "area_used": area_used,
        "weight_used": weight_used,
        "avg_height": avg_height,
    }


def _tray_kpi_lines(
    trays: list,
    sku_by_id: dict,
    affinity_graph,
    config: MicroSlottingConfig,
) -> list[str]:
    from slotting.algorithms.micro.scoring.affinity import pairwise_affinity_sum
    from slotting.algorithms.micro.scoring.height import (
        convex_height_penalty,
        height_diff_by_area_for_skus,
    )
    from slotting.algorithms.micro.scoring.size import size_penalty

    lines: list[str] = []
    for tray in trays:
        units_by_sku: dict[str, float] = {}
        for item in tray.items:
            units_by_sku[item.sku_id] = units_by_sku.get(item.sku_id, 0.0) + float(item.units)
        sku_ids = list(units_by_sku.keys())
        if not sku_ids:
            continue
        affinity = pairwise_affinity_sum(sku_ids, affinity_graph)
        height_diff = height_diff_by_area_for_skus(sku_ids, sku_by_id, units_by_sku)
        height_pen = convex_height_penalty(height_diff, config.group_height_ref, config.group_height_p)
        size_pen = size_penalty(len(sku_ids), config.subgroup_size_gamma, config.subgroup_size_p)
        kpi = affinity - config.subgroup_height_weight * height_pen - size_pen
        lines.append(
            f"{tray.tray_id},{kpi:.6f},{affinity:.6f},{height_pen:.6f},{size_pen:.6f},"
            f"{height_diff:.6f},{len(sku_ids)}"
        )
    return lines


def _affinity_zero_ratio(trays: list, affinity_graph) -> float:
    from slotting.algorithms.micro.scoring.affinity import pairwise_affinity_sum

    if not trays:
        return 0.0
    zero = 0
    for tray in trays:
        sku_ids = [item.sku_id for item in tray.items]
        if not sku_ids:
            continue
        if abs(pairwise_affinity_sum(sku_ids, affinity_graph)) < 1e-9:
            zero += 1
    return zero / len(trays) * 100.0


def _units_by_sku(trays: list) -> dict[str, float]:
    units: dict[str, float] = {}
    for tray in trays:
        for item in tray.items:
            units[item.sku_id] = units.get(item.sku_id, 0.0) + float(item.units)
    return units


def _validate_units_preserved(trays_before: list, trays_after: list) -> None:
    before_units = _units_by_sku(trays_before)
    after_units = _units_by_sku(trays_after)
    mismatches: list[tuple[str, float, float]] = []
    for sku_id, units in before_units.items():
        after = after_units.get(sku_id, 0.0)
        if abs(units - after) > 1e-6:
            mismatches.append((sku_id, units, after))
    if mismatches:
        sample = ", ".join(
            f"{sku_id}:{before}->{after}" for sku_id, before, after in mismatches[:10]
        )
        raise ValueError(
            f"Units mismatch after optimization: {len(mismatches)} SKUs differ. Sample: {sample}"
        )


def _build_config(
    args: argparse.Namespace,
    default_config: MicroSlottingConfig,
    cycle_days: float,
) -> MicroSlottingConfig:
    return MicroSlottingConfig(
        cycle_days=cycle_days,
        group_seed_count=default_config.group_seed_count
        if args.group_seed_count is None
        else args.group_seed_count,
        group_seed_strategy=default_config.group_seed_strategy
        if args.group_seed_strategy is None
        else args.group_seed_strategy,
        selection_cost_mode=default_config.selection_cost_mode
        if args.selection_cost_mode is None
        else args.selection_cost_mode,
        graph_top_k_neighbors=default_config.graph_top_k_neighbors
        if args.graph_top_k_neighbors is None
        else args.graph_top_k_neighbors,
        graph_aff_min=default_config.graph_aff_min
        if args.graph_aff_min is None
        else args.graph_aff_min,
        group_min_delta=default_config.group_min_delta
        if args.group_min_delta is None
        else args.group_min_delta,
        group_max_size=default_config.group_max_size
        if args.group_max_size is None
        else args.group_max_size,
        group_score_wa=default_config.group_score_wa
        if args.group_score_wa is None
        else args.group_score_wa,
        group_score_wr=default_config.group_score_wr
        if args.group_score_wr is None
        else args.group_score_wr,
        group_score_wh=default_config.group_score_wh
        if args.group_score_wh is None
        else args.group_score_wh,
        group_height_ref=default_config.group_height_ref
        if args.group_height_ref is None
        else args.group_height_ref,
        group_height_p=default_config.group_height_p
        if args.group_height_p is None
        else args.group_height_p,
        subgroup_max_size=default_config.subgroup_max_size
        if args.subgroup_max_size is None
        else args.subgroup_max_size,
        subgroup_size_gamma=default_config.subgroup_size_gamma
        if args.subgroup_size_gamma is None
        else args.subgroup_size_gamma,
        subgroup_size_p=default_config.subgroup_size_p
        if args.subgroup_size_p is None
        else args.subgroup_size_p,
        subgroup_height_weight=default_config.subgroup_height_weight
        if args.subgroup_height_weight is None
        else args.subgroup_height_weight,
        subgroup_seed_pairs_cap=default_config.subgroup_seed_pairs_cap
        if args.subgroup_seed_pairs_cap is None
        else args.subgroup_seed_pairs_cap,
        subgroup_candidate_eval_cap=default_config.subgroup_candidate_eval_cap
        if args.subgroup_candidate_eval_cap is None
        else args.subgroup_candidate_eval_cap,
        subgroup_min_delta=default_config.subgroup_min_delta
        if args.subgroup_min_delta is None
        else args.subgroup_min_delta,
        subgroup_marginal_tray_weight=default_config.subgroup_marginal_tray_weight
        if args.subgroup_marginal_tray_weight is None
        else args.subgroup_marginal_tray_weight,
        subgroup_marginal_area_waste_weight=default_config.subgroup_marginal_area_waste_weight
        if args.subgroup_marginal_area_waste_weight is None
        else args.subgroup_marginal_area_waste_weight,
        subgroup_allow_singleton=default_config.subgroup_allow_singleton
        if not args.subgroup_allow_singleton
        else args.subgroup_allow_singleton,
        subgroup_singleton_strategy=default_config.subgroup_singleton_strategy
        if args.subgroup_singleton_strategy is None
        else args.subgroup_singleton_strategy,
        unassigned_height_delta_max=default_config.unassigned_height_delta_max
        if args.unassigned_height_delta_max is None
        else args.unassigned_height_delta_max,
        unassigned_include=default_config.unassigned_include
        if args.unassigned_include is None
        else args.unassigned_include,
        tray_base_area_max=default_config.tray_base_area_max
        if args.tray_base_area_max is None
        else args.tray_base_area_max,
        tray_weight_max=default_config.tray_weight_max
        if args.tray_weight_max is None
        else args.tray_weight_max,
        tray_op_void=default_config.tray_op_void
        if args.tray_op_void is None
        else args.tray_op_void,
        optimizer_tray_count_weight=default_config.optimizer_tray_count_weight
        if args.optimizer_tray_count_weight is None
        else args.optimizer_tray_count_weight,
        optimizer_area_waste_weight=default_config.optimizer_area_waste_weight
        if args.optimizer_area_waste_weight is None
        else args.optimizer_area_waste_weight,
        max_trays=default_config.max_trays if args.max_trays is None else args.max_trays,
    )


if __name__ == "__main__":
    raise SystemExit(main())
