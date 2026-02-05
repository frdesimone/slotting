from __future__ import annotations

from pathlib import Path

from slotting.algorithms.micro import (
    MicroSlottingConfig,
    build_affinity_graph,
    build_groups,
    build_tray_plans,
    select_groups,
)

from slotting.algorithms.common.prep import (
    load_slotting_inputs_with_stats
)


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    content = "\n".join(",".join(row) for row in rows)
    path.write_text(content, encoding="utf-8")


def test_end_to_end_csv_like_docs(tmp_path: Path) -> None:
    codes_path = tmp_path / "codes.csv"
    orders_path = tmp_path / "orders.csv"

    _write_csv(
        codes_path,
        [
            ["", "", "", "", "", ""],
            ["", "CODIGOS INVOLUCRADOS EN PEDIDOS JUNIO NOVIEMBRE", "", "", "", ""],
            ["", "", "", "", "", ""],
            [
                "",
                "Código II",
                "Q. según pedidos",
                "Promedio VTA",
                "m3 x unidad",
                "Peso [kgrs]",
                "Alto [mm]",
                "Ancho [mm]",
                "Largo [mm]",
            ],
            ["", "1", "  596 ", "  73 ", "  0.0003 ", "  0.18 ", "  17.00 ", "  65.00 ", "  200.00 "],
            ["", "2", "  743 ", "  127 ", "  0.0004 ", "  0.35 ", "  20.00 ", "  80.00 ", "  245.00 "],
            ["", "3", "  2044 ", "  325 ", "  0.0006 ", "  0.50 ", "  23.00 ", "  90.00 ", "  290.00 "],
        ],
    )

    _write_csv(
        orders_path,
        [
            ["Detalle de pedidos del 1/06/2025 al 30/11/2025", "", "", "", "", ""],
            ["", "", "", "", "", ""],
            [
                "Fecha pedido",
                "Nro pedido",
                "Código II - Producto",
                "Cantidad unidades",
                "Mes",
                "Comentarios",
                "Maestro",
            ],
            ["6/13/2025", "284267", "1", "2", "junio", "Ok", "Maestro"],
            ["6/13/2025", "284267", "2", "5", "junio", "Ok", "Maestro"],
            ["6/13/2025", "284268", "1", "1", "junio", "Ok", "Maestro"],
            ["6/13/2025", "284268", "3", "4", "junio", "Ok", "Maestro"],
            ["6/14/2025", "284269", "2", "3", "junio", "Ok", "Maestro"],
        ],
    )

    config = MicroSlottingConfig(
        group_seed_count=1,
        graph_top_k_neighbors=3,
        graph_aff_min=0.0,
        group_min_delta=0.0,
        group_max_size=3,
        group_score_wa=1.0,
        group_score_wr=0.0,
        group_score_wh=0.0,
        subgroup_allow_singleton=True,
        subgroup_singleton_strategy="allow_singleton",
        unassigned_include=False,
    )

    skus, orders, _ = load_slotting_inputs_with_stats(
        codes_csv_path=codes_path,
        orders_csv_path=orders_path,
        cycle_days=config.cycle_days,
        period_days=180.0,
        include_zero_rot=False,
    )
    affinity_graph = build_affinity_graph(
        orders=orders,
        top_k=config.graph_top_k_neighbors,
        aff_min=config.graph_aff_min,
        metric=config.affinity_metric,
    )
    groups = build_groups(skus=skus, orders=orders, config=config)
    selected_groups = select_groups(groups=groups, skus=skus)
    plans = build_tray_plans(
        selected_groups=selected_groups,
        skus=skus,
        affinity_graph=affinity_graph,
        config=config,
    )

    assert plans
    trays = [tray for plan in plans for tray in plan.trays]
    assert trays
    for tray in trays:
        assert tray.area_used <= tray.max_area + 1e-6
        assert tray.weight_used <= tray.max_weight + 1e-6
