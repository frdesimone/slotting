from __future__ import annotations

import math

from slotting.algorithms.micro.config import MicroSlottingConfig
from slotting.algorithms.micro.group_score import estimate_cycle_units
from slotting.algorithms.micro.utils import sku_unit_area_mm2, tray_capacity
from slotting.models import SKU, Subgroup, Tray, TrayItem


def build_trays_for_subgroup(
    subgroup: Subgroup,
    sku_by_id: dict[str, SKU],
    config: MicroSlottingConfig,
    max_trays_limit: int | None = None,
) -> list[Tray]:
    """Allocate cycle units into the minimum number of trays for the subgroup."""
    context = _build_allocation_context(subgroup, sku_by_id, config, max_trays_limit)
    _validate_unit_fit(subgroup, context)
    _fill_trays_to_target(
        trays=context["trays"],
        ordered_skus=context["ordered_skus"],
        remaining_units=context["remaining_units"],
        unit_area=context["unit_area"],
        unit_weight=context["unit_weight"],
        unit_volume=context["unit_volume"],
        heights=context["heights"],
        target_area=context["target_area"],
        max_area=context["max_area"],
        max_weight=context["max_weight"],
        config=config,
    )
    _fill_trays_to_capacity(
        trays=context["trays"],
        ordered_skus=context["ordered_skus"],
        remaining_units=context["remaining_units"],
        unit_area=context["unit_area"],
        unit_weight=context["unit_weight"],
        unit_volume=context["unit_volume"],
        heights=context["heights"],
        max_area=context["max_area"],
        max_weight=context["max_weight"],
        config=config,
    )
    trays = _append_extra_trays_if_needed(
        trays=context["trays"],
        subgroup=subgroup,
        remaining_units=context["remaining_units"],
        ordered_skus=context["ordered_skus"],
        unit_area=context["unit_area"],
        unit_weight=context["unit_weight"],
        unit_volume=context["unit_volume"],
        heights=context["heights"],
        max_area=context["max_area"],
        max_weight=context["max_weight"],
        config=config,
        max_trays_limit=context["max_trays_limit"],
    )
    _ensure_all_units_allocated(
        context["remaining_units"],
        subgroup,
        len(context["trays"]),
        context["max_trays_limit"],
    )
    return _filter_empty_trays(trays, subgroup)


def _init_empty_tray(
    subgroup: Subgroup,
    index: int,
    max_area: float,
    max_weight: float,
) -> Tray:
    return Tray(
        tray_id=f"{subgroup.group_id}-{subgroup.subgroup_id}-t{index}",
        group_id=subgroup.group_id,
        subgroup_id=subgroup.subgroup_id,
        height=0.0,
        max_area=max_area,
        max_weight=max_weight,
        area_used=0.0,
        weight_used=0.0,
        items=[],
    )


def _fill_tray_to_target(
    tray: Tray,
    ordered_skus: list[str],
    remaining_units: dict[str, float],
    unit_area: dict[str, float],
    unit_weight: dict[str, float],
    unit_volume: dict[str, float],
    heights: dict[str, float],
    target_area: float,
    max_area: float,
    max_weight: float,
    config: MicroSlottingConfig,
) -> None:
    """Greedy fill to a target area while respecting tray capacity."""
    desired_area = min(target_area, max_area)

    _fill_tray(
        tray=tray,
        ordered_skus=ordered_skus,
        remaining_units=remaining_units,
        unit_area=unit_area,
        unit_weight=unit_weight,
        unit_volume=unit_volume,
        heights=heights,
        max_area=desired_area,
        max_weight=max_weight,
        config=config,
    )


def _fill_tray_to_capacity(
    tray: Tray,
    ordered_skus: list[str],
    remaining_units: dict[str, float],
    unit_area: dict[str, float],
    unit_weight: dict[str, float],
    unit_volume: dict[str, float],
    heights: dict[str, float],
    max_area: float,
    max_weight: float,
    config: MicroSlottingConfig,
) -> None:
    """Second pass to fill remaining units up to full capacity."""
    _fill_tray(
        tray=tray,
        ordered_skus=ordered_skus,
        remaining_units=remaining_units,
        unit_area=unit_area,
        unit_weight=unit_weight,
        unit_volume=unit_volume,
        heights=heights,
        max_area=max_area,
        max_weight=max_weight,
        config=config,
    )


def _fill_tray(
    tray: Tray,
    ordered_skus: list[str],
    remaining_units: dict[str, float],
    unit_area: dict[str, float],
    unit_weight: dict[str, float],
    unit_volume: dict[str, float],
    heights: dict[str, float],
    max_area: float,
    max_weight: float,
    config: MicroSlottingConfig,
) -> None:
    for sku_id in ordered_skus:
        if not config.is_multiproduct and tray.items:
            existing_skus = {item.sku_id for item in tray.items}
            if existing_skus and sku_id not in existing_skus:
                continue

        units_left = remaining_units.get(sku_id, 0.0)
        if units_left <= 0:
            continue

        area_left = max_area - tray.area_used
        weight_left = max_weight - tray.weight_used
        if area_left <= 1e-9 or weight_left <= 1e-9:
            break

        unit_h = heights[sku_id]
        # config max_h_* en m; heights en mm → convertir a mm para consistencia
        max_h_loc_mm = config.max_h_loc * 1000.0 if config.max_h_loc > 0 else float("inf")
        max_h_storage_mm = config.max_h_storage * 1000.0 if config.max_h_storage > 0 else float("inf")
        if config.is_variable_height:
            h_limit = max(tray.height, unit_h)
            if max_h_storage_mm < float("inf"):
                h_limit = min(h_limit, max_h_storage_mm)
        else:
            h_limit = max_h_loc_mm

        max_vertical = int(h_limit // unit_h) if unit_h > 0 else 1
        if max_vertical < 1:
            max_vertical = 1
        actual_stack = min(config.stackability_factor, max_vertical)

        add_units = _max_units_that_fit(
            units_left=units_left,
            area_left=area_left,
            weight_left=weight_left,
            unit_area=unit_area[sku_id],
            unit_weight=unit_weight[sku_id],
            actual_stack=actual_stack,
        )
        if add_units <= 0:
            continue
        _add_units_to_tray(
            tray=tray,
            sku_id=sku_id,
            add_units=add_units,
            unit_area=unit_area[sku_id],
            unit_weight=unit_weight[sku_id],
            unit_volume=unit_volume[sku_id],
            height=unit_h,
            actual_stack=actual_stack,
        )
        remaining_units[sku_id] = units_left - add_units


def _max_units_that_fit(
    units_left: float,
    area_left: float,
    weight_left: float,
    unit_area: float,
    unit_weight: float,
    actual_stack: int,
) -> float:
    if unit_area <= 0 and unit_weight <= 0:
        return float(math.floor(units_left))
    area_limit = units_left
    if unit_area > 0:
        max_footprints = math.floor(area_left / unit_area)
        area_limit = float(max_footprints * actual_stack)
    weight_limit = units_left
    if unit_weight > 0:
        weight_limit = min(weight_limit, weight_left / unit_weight)
    limit = min(units_left, area_limit, weight_limit)
    return max(0.0, float(math.floor(limit)))


def _add_units_to_tray(
    tray: Tray,
    sku_id: str,
    add_units: float,
    unit_area: float,
    unit_weight: float,
    unit_volume: float,
    height: float,
    actual_stack: int,
) -> None:
    stacks_needed = math.ceil(add_units / actual_stack) if actual_stack > 0 else add_units
    total_area = stacks_needed * unit_area
    total_weight = add_units * unit_weight
    total_volume = add_units * unit_volume
    tray.area_used += total_area
    tray.weight_used += total_weight
    tray.height = max(tray.height, height)
    tray.items.append(
        TrayItem(
            sku_id=sku_id,
            units=add_units,
            unit_volume=unit_volume,
            unit_weight=unit_weight,
            total_volume=total_volume,
            total_weight=total_weight,
            unit_area=unit_area,
            total_area=total_area,
        )
    )


def _build_sku_metrics(
    sku_ids: list[str],
    sku_by_id: dict[str, SKU],
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
    unit_area = {sku_id: sku_unit_area_mm2(sku_by_id[sku_id]) for sku_id in sku_ids}
    unit_weight = {sku_id: sku_by_id[sku_id].weight for sku_id in sku_ids}
    unit_volume = {sku_id: sku_by_id[sku_id].volume for sku_id in sku_ids}
    heights = {sku_id: sku_by_id[sku_id].height for sku_id in sku_ids}
    cycle_units = {sku_id: estimate_cycle_units(sku_by_id[sku_id]) for sku_id in sku_ids}
    return unit_area, unit_weight, unit_volume, heights, cycle_units


def _compute_totals(
    sku_ids: list[str],
    cycle_units: dict[str, float],
    unit_area: dict[str, float],
    unit_weight: dict[str, float],
) -> tuple[float, float]:
    total_area = sum(cycle_units[sku_id] * unit_area[sku_id] for sku_id in sku_ids)
    total_weight = sum(cycle_units[sku_id] * unit_weight[sku_id] for sku_id in sku_ids)
    return total_area, total_weight


def _tray_count(
    total_area: float,
    total_weight: float,
    max_area: float,
    max_weight: float,
    max_trays_limit: int,
    subgroup: Subgroup,
) -> int:
    trays_area = max(1, math.ceil(total_area / max_area)) if total_area > 0 else 1
    trays_weight = max(1, math.ceil(total_weight / max_weight)) if total_weight > 0 else 1
    tray_count = max(trays_area, trays_weight, 1)
    if tray_count > max_trays_limit:
        print(f"⚠️ [Subgrupo {subgroup.subgroup_id}] Requiere {tray_count} bandejas, superando max_trays_limit de {max_trays_limit}. Creando bandejas adicionales...")
    return tray_count


def _init_trays(
    subgroup: Subgroup,
    tray_count: int,
    max_area: float,
    max_weight: float,
) -> list[Tray]:
    return [
        _init_empty_tray(subgroup, idx + 1, max_area, max_weight)
        for idx in range(tray_count)
    ]


def _fill_trays_to_target(
    trays: list[Tray],
    ordered_skus: list[str],
    remaining_units: dict[str, float],
    unit_area: dict[str, float],
    unit_weight: dict[str, float],
    unit_volume: dict[str, float],
    heights: dict[str, float],
    target_area: float,
    max_area: float,
    max_weight: float,
    config: MicroSlottingConfig,
) -> None:
    for tray in trays:
        _fill_tray_to_target(
            tray=tray,
            ordered_skus=ordered_skus,
            remaining_units=remaining_units,
            unit_area=unit_area,
            unit_weight=unit_weight,
            unit_volume=unit_volume,
            heights=heights,
            target_area=target_area,
            max_area=max_area,
            max_weight=max_weight,
            config=config,
        )


def _fill_trays_to_capacity(
    trays: list[Tray],
    ordered_skus: list[str],
    remaining_units: dict[str, float],
    unit_area: dict[str, float],
    unit_weight: dict[str, float],
    unit_volume: dict[str, float],
    heights: dict[str, float],
    max_area: float,
    max_weight: float,
    config: MicroSlottingConfig,
) -> None:
    if any(units > 1e-9 for units in remaining_units.values()):
        for tray in trays:
            _fill_tray_to_capacity(
                tray=tray,
                ordered_skus=ordered_skus,
                remaining_units=remaining_units,
                unit_area=unit_area,
                unit_weight=unit_weight,
                unit_volume=unit_volume,
                heights=heights,
                max_area=max_area,
                max_weight=max_weight,
                config=config,
            )


def _append_extra_trays_if_needed(
    trays: list[Tray],
    subgroup: Subgroup,
    remaining_units: dict[str, float],
    ordered_skus: list[str],
    unit_area: dict[str, float],
    unit_weight: dict[str, float],
    unit_volume: dict[str, float],
    heights: dict[str, float],
    max_area: float,
    max_weight: float,
    config: MicroSlottingConfig,
    max_trays_limit: int,
) -> list[Tray]:
    if any(units > 1e-6 for units in remaining_units.values()):
        while any(units > 1e-6 for units in remaining_units.values()):
            extra_tray = _init_empty_tray(subgroup, len(trays) + 1, max_area, max_weight)
            _fill_tray_to_capacity(
                tray=extra_tray,
                ordered_skus=ordered_skus,
                remaining_units=remaining_units,
                unit_area=unit_area,
                unit_weight=unit_weight,
                unit_volume=unit_volume,
                heights=heights,
                max_area=max_area,
                max_weight=max_weight,
                config=config,
            )
            if extra_tray.items:
                trays.append(extra_tray)
                if len(trays) > max_trays_limit:
                    print(f"⚠️ [Recorte] Se excedió el límite. Recortando de {len(trays)} a {max_trays_limit} bandejas.")
                    trays = trays[:max_trays_limit]
                    break
            else:
                break
    return trays


def _ensure_all_units_allocated(
    remaining_units: dict[str, float],
    subgroup: Subgroup,
    trays_count: int,
    max_trays_limit: int,
) -> None:
    if any(units > 1e-6 for units in remaining_units.values()):
        leftovers = {sku_id: units for sku_id, units in remaining_units.items() if units > 1e-6}
        print(f"⚠️ [Subgrupo {subgroup.subgroup_id}] Cuidado: No se pudieron ubicar todas las unidades. Quedaron pendientes: {leftovers}")


def _filter_empty_trays(trays: list[Tray], subgroup: Subgroup) -> list[Tray]:
    trays = [tray for tray in trays if tray.items]
    if not trays:
        print(f"⚠️ [Subgrupo {subgroup.subgroup_id}] No se generaron bandejas. Devolviendo lista vacía.")
    return trays


def _build_allocation_context(
    subgroup: Subgroup,
    sku_by_id: dict[str, SKU],
    config: MicroSlottingConfig,
    max_trays_limit: int | None,
) -> dict[str, object]:
    max_trays_effective = config.max_trays if max_trays_limit is None else max_trays_limit
    sku_ids = subgroup.sku_ids
    unit_area, unit_weight, unit_volume, heights, cycle_units = _build_sku_metrics(
        sku_ids, sku_by_id
    )
    total_area, total_weight = _compute_totals(sku_ids, cycle_units, unit_area, unit_weight)
    max_area, max_weight = tray_capacity(
        config.tray_base_area_max, config.tray_op_void, config.tray_weight_max
    )
    tray_count = _tray_count(
        total_area, total_weight, max_area, max_weight, max_trays_effective, subgroup
    )
    target_area = total_area / tray_count if tray_count > 0 else total_area
    remaining_units = dict(cycle_units)
    trays = _init_trays(subgroup, tray_count, max_area, max_weight)
    ordered_skus = sorted(sku_ids, key=lambda s: (-heights[s], s))
    return {
        "unit_area": unit_area,
        "unit_weight": unit_weight,
        "unit_volume": unit_volume,
        "heights": heights,
        "cycle_units": cycle_units,
        "max_area": max_area,
        "max_weight": max_weight,
        "target_area": target_area,
        "remaining_units": remaining_units,
        "trays": trays,
        "ordered_skus": ordered_skus,
        "max_trays_limit": max_trays_effective,
    }


def _validate_unit_fit(subgroup: Subgroup, context: dict[str, object]) -> None:
    max_area = context["max_area"]
    max_weight = context["max_weight"]
    unit_area = context["unit_area"]
    unit_weight = context["unit_weight"]
    for sku_id in subgroup.sku_ids:
        area = unit_area[sku_id]
        weight = unit_weight[sku_id]
        if area > max_area:
            print(
                f"⚠️ [Subgrupo {subgroup.subgroup_id}] Unidad excede capacidad de bandeja: "
                f"sku_id={sku_id} unit_area={area:.2f} > max_area={max_area:.2f}"
            )
        if weight > max_weight:
            print(
                f"⚠️ [Subgrupo {subgroup.subgroup_id}] Unidad excede capacidad de bandeja: "
                f"sku_id={sku_id} unit_weight={weight:.2f} > max_weight={max_weight:.2f}"
            )
