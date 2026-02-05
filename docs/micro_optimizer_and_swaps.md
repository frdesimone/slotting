## Micro optimizer + swaps (standalone/híbrido)

Este documento describe:
- API de swaps/relocates (lógico + físico).
- Uso del optimizador local (pipeline o standalone).
- Formatos de entrada para estado existente (CSV y JSON).

### API de moves

Moves soportados:
- `swap`: intercambia dos SKUs entre subgrupos distintos.
- `relocate`: mueve un SKU de un subgrupo a otro.

Formato JSON (para uso manual):
```json
[
  {"type": "swap", "sku_a": "A", "sku_b": "B"},
  {"type": "relocate", "sku_id": "C", "from_subgroup_id": "g1-h1", "to_subgroup_id": "g2-h1"}
]
```

Reglas:
- Un subgrupo no puede quedar vacío.
- `subgroup_max_size` es hard.
- Validación física local:
  - capacidad de bandeja
  - `max_trays` (global)
  - no bandejas vacías

### Estado híbrido (lógico + físico)

La API principal para optimización es:
- `build_hybrid_kpi_state(...)` en `kpi_state/api.py`.

El estado híbrido:
- Recalcula KPI lógico incremental.
- Valida físicamente solo subgrupos afectados por un move.
- KPI global incluye penalización física configurable:
  - `optimizer_tray_count_weight * tray_count`
  - `optimizer_area_waste_weight * area_waste_ratio`

### Optimización local

Implementación:
`src/slotting/algorithms/micro/optimization/optimizer.py`

Parámetros principales:
- `iterations`, `time_budget_ms`
- `seed`
- `allow_annealing`, `temp_start`, `temp_end`
- `log_every`, `log_path`, `trace_path`
- `--opt-report-breakdown` (incluye KPI por bandeja en el reporte)

Outputs por default:
- `outputs/optimizer.log`
- `outputs/optimizer_trace.csv`
- `outputs/optimizer_report.txt`
- `outputs/trays_optimized.csv`

Notas de reporte:
- El breakdown de KPI es por bandeja (tray-level), no por subgrupo lógico.
- Se puede habilitar con `--opt-report-breakdown` (por defecto queda compacto).

### Standalone (sin pipeline)

#### Opción A: `trays.csv` + `affinity_graph.json`
Reutiliza el formato exportado por Step 7.

```bash
python scripts/run_micro_optimizer.py \
  --input-mode trays \
  --input-trays-csv outputs/trays.csv \
  --affinity-graph-json outputs/affinity_graph.json \
  --codes-csv docs/Base\ de\ códigos\ -\ semestre\ jun-nov\ \ (11-1-2026)\ -\ Std\ Logix.xlsx\ -\ Base\ cód.\ segun\ pedidos-final.csv
```

Opcional:
- `--sku-rot-csv` con columnas `sku_id,rot` para preservar rotación por líneas.
- Si no se provee, `rot` se aproxima con unidades por SKU.

#### Opción B: snapshot JSON
```bash
python scripts/run_micro_optimizer.py --input-mode state-json --state-json outputs/state.json
```

Notas:
- El snapshot JSON serializa solo campos simples del config.
- Estrategias custom (`affinity_metric`, `affinity_scorer`, `candidate_selector`) no se serializan.

Ejemplo mínimo de `state.json`:
```json
{
  "config": {"group_max_size": 16, "subgroup_max_size": 10, "max_trays": 256},
  "skus": [
    {"sku_id": "A", "rot": 1, "height": 10, "volume": 1e-6, "weight": 1, "cycle_units": 1}
  ],
  "affinity_graph": {"A": []},
  "subgroups": [{"subgroup_id": "g1-h1", "group_id": "g1", "sku_ids": ["A"], "score": 0}],
  "trays": [
    {
      "tray_id": "g1-g1-h1-t1",
      "group_id": "g1",
      "subgroup_id": "g1-h1",
      "height": 10,
      "max_area": 1000,
      "max_weight": 1000,
      "area_used": 100,
      "weight_used": 1,
      "items": [{"sku_id": "A", "units": 1, "unit_volume": 1e-6, "unit_weight": 1, "unit_area": 100}]
    }
  ]
}
```

#### Aplicar moves manuales (sin optimizar)
```bash
python scripts/run_micro_optimizer.py \
  --input-mode state-json \
  --state-json outputs/state.json \
  --moves-json outputs/moves.json \
  --apply-only \
  --state-out-json outputs/state_updated.json
```
