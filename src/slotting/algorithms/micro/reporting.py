from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from slotting.algorithms.micro.group_score import estimate_cycle_units, group_cost_cycle_volume
from slotting.algorithms.micro.scoring.height import height_diff_by_area_for_tray
from slotting.models import AffinityGroup, Order, SKU, TrayPlan


@dataclass(frozen=True)
class RunReport:
    lines: list[str]


def build_run_report(
    skus: list[SKU],
    orders: list[Order],
    groups: list[AffinityGroup],
    selected_groups: list[AffinityGroup],
    tray_plans: list[TrayPlan],
    stats: object,
) -> RunReport:
    context = _build_report_context(skus, selected_groups, tray_plans)
    lines: list[str] = []
    _append_header(lines, skus, stats)
    _append_order_stats(lines, orders, stats)
    _append_group_stats(lines, groups, selected_groups, context["selected_skus"], skus)
    _append_cycle_stats(
        lines,
        context["selected_skus"],
        context["total_cycle_volume"],
        context["selected_cycle_volume"],
        context["total_cycle_weight"],
        context["sku_by_id"],
    )
    _append_tray_stats(
        lines,
        context["trays_count"],
        context["subgroups_count"],
        context["tray_sku_ids"],
        skus,
        context["unassigned_sku_ids"],
        context["tray_assigned_volume"],
        context["tray_assigned_weight"],
        context["total_cycle_volume"],
        context["total_cycle_weight"],
        context["area_used"],
        context["area_capacity"],
        context["area_waste"],
        context["weight_used"],
        context["weight_capacity"],
        context["weight_waste"],
        context["all_trays"],
    )

    return RunReport(lines=lines)


def _append_header(lines: list[str], skus: list[SKU], stats: object) -> None:
    lines.append("Micro-slotting V1 (hasta Paso 7)")
    lines.append(
        f"- SKUs input: {len(skus)} "
        f"(excluidos: missing={getattr(stats, 'skipped_missing_data', 0)}, "
        f"zero_rot={getattr(stats, 'skipped_zero_rot', 0)})"
    )


def _append_order_stats(lines: list[str], orders: list[Order], stats: object) -> None:
    order_stats = getattr(stats, "order_stats", None)
    if order_stats is not None:
        lines.append(
            f"- Orders raw: {order_stats.total_orders} "
            f"(lines kept {order_stats.kept_rows}, "
            f"skipped missing fields {order_stats.skipped_missing_fields}, "
            f"skipped missing master {order_stats.skipped_missing_master})"
        )
    lines.append(
        f"- Orders after SKU filter: {len(orders)} "
        f"(filtered_empty={getattr(stats, 'orders_filtered_empty', 0)})"
    )


def _append_group_stats(
    lines: list[str],
    groups: list[AffinityGroup],
    selected_groups: list[AffinityGroup],
    selected_skus: set[str],
    skus: list[SKU],
) -> None:
    avg_group_size = sum(len(g.sku_ids) for g in groups) / max(len(groups), 1)
    selected_avg_group_size = sum(len(g.sku_ids) for g in selected_groups) / max(
        len(selected_groups), 1
    )
    lines.append(f"- Groups generated: {len(groups)} (avg size {avg_group_size:.2f})")
    lines.append("Paso 6 (seleccion logica):")
    lines.append(
        f"- Groups selected: {len(selected_groups)} "
        f"(avg size {selected_avg_group_size:.2f})"
    )
    lines.append(
        f"- SKUs selected: {len(selected_skus)} / {len(skus)} "
        f"({(len(selected_skus) / len(skus) * 100.0) if skus else 0.0:.1f}%)"
    )


def _append_cycle_stats(
    lines: list[str],
    selected_skus: set[str],
    total_cycle_volume: float,
    selected_cycle_volume: float,
    total_cycle_weight: float,
    sku_by_id: dict[str, SKU],
) -> None:
    lines.append(
        f"- Cycle volume total: {total_cycle_volume:.4f} m3 | "
        f"selected: {selected_cycle_volume:.4f} m3 "
        f"({(selected_cycle_volume / total_cycle_volume * 100.0) if total_cycle_volume else 0.0:.1f}%)"
    )
    lines.append(
        f"- Cycle weight total: {total_cycle_weight:.2f} kg | "
        f"selected: {sum(estimate_cycle_units(sku_by_id[sku_id]) * sku_by_id[sku_id].weight for sku_id in selected_skus):.2f} kg"
    )


def _append_tray_stats(
    lines: list[str],
    trays_count: int,
    subgroups_count: int,
    tray_sku_ids: set[str],
    skus: list[SKU],
    unassigned_sku_ids: set[str],
    tray_assigned_volume: float,
    tray_assigned_weight: float,
    total_cycle_volume: float,
    total_cycle_weight: float,
    area_used: float,
    area_capacity: float,
    area_waste: float,
    weight_used: float,
    weight_capacity: float,
    weight_waste: float,
    all_trays: list,
) -> None:
    lines.append("Paso 7 (bandejas fisicas):")
    lines.append(f"- Subgroups: {subgroups_count} | Trays: {trays_count}")
    lines.append(
        f"- SKUs in trays: {len(tray_sku_ids)} / {len(skus)} "
        f"({(len(tray_sku_ids) / len(skus) * 100.0) if skus else 0.0:.1f}%)"
    )
    lines.append(f"- SKUs unassigned to trays: {len(unassigned_sku_ids)}")
    lines.append(
        f"- Cycle volume assigned: {tray_assigned_volume:.4f} m3 "
        f"({(tray_assigned_volume / total_cycle_volume * 100.0) if total_cycle_volume else 0.0:.1f}%)"
    )
    lines.append(
        f"- Cycle weight assigned: {tray_assigned_weight:.2f} kg "
        f"({(tray_assigned_weight / total_cycle_weight * 100.0) if total_cycle_weight else 0.0:.1f}%)"
    )
    lines.append(
        f"- Tray base area used: {area_used:.2f} / {area_capacity:.2f} mm2 "
        f"(waste {area_waste:.2f} mm2, {(area_waste / area_capacity * 100.0) if area_capacity else 0.0:.1f}%)"
    )
    lines.append(
        f"- Tray weight used: {weight_used:.2f} / {weight_capacity:.2f} kg "
        f"(waste {weight_waste:.2f} kg, {(weight_waste / weight_capacity * 100.0) if weight_capacity else 0.0:.1f}%)"
    )
    lines.append(
        f"- Height waste ratio (area-weighted): {_tray_height_waste_ratio_weighted(all_trays) * 100.0:.1f}%"
    )


def _tray_height_waste_ratio_weighted(all_trays: list) -> float:
    weighted = 0.0
    total = 0.0
    for tray in all_trays:
        if tray.height <= 0:
            continue
        total_area = sum(item.total_area for item in tray.items)
        if total_area <= 0:
            continue
        height_waste = height_diff_by_area_for_tray(tray)
        ratio = height_waste / tray.height
        weighted += ratio * tray.area_used
        total += tray.area_used
    if total <= 0:
        return 0.0
    return weighted / total


def _build_report_context(
    skus: list[SKU],
    selected_groups: list[AffinityGroup],
    tray_plans: list[TrayPlan],
) -> dict[str, object]:
    sku_by_id = {sku.sku_id: sku for sku in skus}
    selected_skus = {sku_id for g in selected_groups for sku_id in g.sku_ids}
    selected_cycle_volume = sum(
        group_cost_cycle_volume(g.sku_ids, sku_by_id) for g in selected_groups
    )
    total_cycle_volume = sum(estimate_cycle_units(sku) * sku.volume for sku in skus)
    total_cycle_weight = sum(estimate_cycle_units(sku) * sku.weight for sku in skus)
    all_trays = [tray for plan in tray_plans for tray in plan.trays]
    tray_sku_ids = {item.sku_id for tray in all_trays for item in tray.items}
    unassigned_sku_ids = {sku.sku_id for sku in skus} - tray_sku_ids
    tray_assigned_volume = sum(
        item.total_volume for tray in all_trays for item in tray.items
    )
    tray_assigned_weight = sum(
        item.total_weight for tray in all_trays for item in tray.items
    )
    subgroups_count = sum(len(plan.subgroups) for plan in tray_plans)
    trays_count = len(all_trays)
    area_capacity = sum(tray.max_area for tray in all_trays)
    area_used = sum(tray.area_used for tray in all_trays)
    area_waste = max(area_capacity - area_used, 0.0)
    weight_capacity = sum(tray.max_weight for tray in all_trays)
    weight_used = sum(tray.weight_used for tray in all_trays)
    weight_waste = max(weight_capacity - weight_used, 0.0)
    return {
        "sku_by_id": sku_by_id,
        "selected_skus": selected_skus,
        "selected_cycle_volume": selected_cycle_volume,
        "total_cycle_volume": total_cycle_volume,
        "total_cycle_weight": total_cycle_weight,
        "all_trays": all_trays,
        "tray_sku_ids": tray_sku_ids,
        "unassigned_sku_ids": unassigned_sku_ids,
        "tray_assigned_volume": tray_assigned_volume,
        "tray_assigned_weight": tray_assigned_weight,
        "subgroups_count": subgroups_count,
        "trays_count": trays_count,
        "area_capacity": area_capacity,
        "area_used": area_used,
        "area_waste": area_waste,
        "weight_capacity": weight_capacity,
        "weight_used": weight_used,
        "weight_waste": weight_waste,
    }
