
# slotting

Repo base para el proyecto de slotting.

## Setup

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Micro-slotting V1 (afinidades)

Entrada esperada (ya procesada, sin leer CSVs en esta etapa):
- `skus`: lista de `SKU` con `rot`, `height`, `volume`, `weight`
- `orders`: lista de `Order` con `sku_ids`

Ejemplo de uso:

```python
from slotting.algorithms.micro import (
    MicroSlottingConfig,
    build_groups,
    load_micro_slotting_inputs,
    select_groups,
)

config = MicroSlottingConfig()
skus, orders = load_micro_slotting_inputs(
    codes_csv_path="docs/Base de códigos - semestre jun-nov  (11-1-2026) - Std Logix.xlsx - Base cód. segun pedidos-final.csv",
    orders_csv_path="docs/Base de pedidos - semestre jun-nov  (2-1-2026) - Std Logix.xlsx - Consolidado pedidos.csv",
    cycle_days=config.cycle_days,
    period_days=180.0,
)
groups = build_groups(skus=skus, orders=orders, config=config)
selected_groups = select_groups(groups=groups, skus=skus)
```

Notas:
- `rot` es por lineas (conteo de filas) y `cycle_units` se calcula como `sum(unidades) * (cycle_days / period_days)`.
- Si `cycle_units` falta en un `SKU`, se usa `rot` como fallback.
- SKUs sin datos completos en el master se excluyen.
- `Cantidad unidades` se usa tal cual; no hay conversion por inner/master.

### Flujo de prep (resumen)

1) Cargar master de códigos y normalizar campos.
2) Cargar pedidos y contar `rot` (líneas) + `unidades`.
3) Calcular `cycle_units` y filtrar SKUs incompletos.
4) Filtrar pedidos vacíos tras el cruce con SKUs válidos.

### Flujo de micro-slotting (resumen)

1) Construir el grafo de afinidades (Jaccard + top-K + aff_min).
2) Elegir seeds con estrategia estratificada y generar grupos con greedy.
3) Scoring de grupo (afinidad + rotación - penalización de altura).
4) Deduplicación y selección sin solapamientos (Paso 6, por score por defecto).
5) Paso 7: subgrupos + bandejas físicas (capacidad por base + peso).
6) Opcional: SKU no asignados (fuera de Paso 6) se empaquetan por altura/afinidad si `include_unassigned_skus` está activo.
7) Opcional: Optimización local con swaps/relocates (greedy + annealing) usando KPI híbrido (lógico + físico).

### Modulos principales

- `src/slotting/algorithms/micro/grouping.py`: afinidades + grupos lógicos.
- `src/slotting/algorithms/micro/selection.py`: selección de grupos (Paso 6).
- `src/slotting/algorithms/micro/step7/`: subgrupos + bandejas (Paso 7).
- `src/slotting/algorithms/micro/kpi_state/`: KPI incremental y validación híbrida.
- `src/slotting/algorithms/micro/optimization/`: optimización local.

Unidades:
- Altura (`height`) en mm.
- Volumen (`volume`) en m³.
- Área base se deriva como `volume / height` y se expresa en mm².
- Capacidad base de bandeja por defecto: 4100 x 857 mm = 3,513,700 mm².
- Para SKUs no asignados, se usa un delta máximo de altura configurable (`unassigned_height_delta_max`).
- `cycle_units` se redondea hacia arriba (`ceil`).
- La asignación física usa unidades enteras (`floor`) por bandeja.

Detalles completos: `docs/micro_slotting_v1.md`.
Optimizador y swaps: `docs/micro_optimizer_and_swaps.md`.

### Limitaciones actuales

- Afinidades `O(n^2)` por pedido: órdenes muy grandes pueden tardar mucho.
- La salida física a bandejas (Paso 7) es un primer heurístico y puede ajustarse.
- Paso 7 puede exportar bandejas a CSV (`--trays-csv`).
- SKUs sin altura/volumen/peso se excluyen del proceso.

### Ejecucion rapida con CSVs locales

```bash
python scripts/run_micro_slotting.py
```

Parametros utiles: `--cycle-days`, `--period-days`, `--group-seed-count`, `--group-seed-strategy`,
`--graph-top-k-neighbors`, `--graph-aff-min`, `--group-max-size`, `--selection-cost-mode`.
- El output son `AffinityGroup` en memoria (aun sin salida fisica).

Nuevos parametros (Paso 7):
- `--subgroup-max-size`, `--subgroup-size-gamma`, `--subgroup-size-p`, `--subgroup-height-weight`
- `--subgroup-min-delta`
- `--subgroup-marginal-tray-weight`, `--subgroup-marginal-area-waste-weight`
- `--unassigned-height-delta-max` (para re-asignar SKUs no seleccionados)
- `--unassigned-include`
- `--no-unassigned-include`
- `--tray-base-area-max`, `--tray-weight-max`, `--tray-op-void`, `--trays-csv`
- `--max-trays`

Optimizacion (pipeline):
- `--optimize`
- `--opt-iterations`, `--opt-time-budget-ms`, `--opt-seed`, `--opt-anneal`
- `--opt-temp-start`, `--opt-temp-end`, `--opt-log-every`
- `--opt-log-path`, `--opt-trace-path`, `--opt-trays-csv`, `--opt-report-path`
- `--optimizer-tray-count-weight`, `--optimizer-area-waste-weight`

Optimizacion (standalone):
```bash
python scripts/run_micro_optimizer.py --opt-iterations 20000 --opt-anneal
```

Standalone con estado existente (trays.csv + affinity_graph.json):
```bash
python scripts/run_micro_optimizer.py \
  --input-mode trays \
  --input-trays-csv outputs/trays.csv \
  --affinity-graph-json outputs/affinity_graph.json \
  --codes-csv docs/Base\ de\ códigos\ -\ semestre\ jun-nov\ \ (11-1-2026)\ -\ Std\ Logix.xlsx\ -\ Base\ cód.\ segun\ pedidos-final.csv
```
Opcional: `--sku-rot-csv` con columnas `sku_id,rot` para preservar rotación por líneas.

Standalone con snapshot JSON:
```bash
python scripts/run_micro_optimizer.py --input-mode state-json --state-json outputs/state.json
```

Aplicar moves manuales (sin optimizar):
```bash
python scripts/run_micro_optimizer.py --input-mode state-json --state-json outputs/state.json \
  --moves-json outputs/moves.json --apply-only --state-out-json outputs/state_updated.json
```

Outputs:
- `outputs/optimizer.log`
- `outputs/optimizer_trace.csv`
- `outputs/optimizer_report.txt`
- `outputs/trays_optimized.csv`
- `outputs/affinity_graph.json`

Nota: el breakdown por bandeja en `optimizer_report.txt` se habilita con `--opt-report-breakdown`.

### Valores por defecto (config)

Ver `src/slotting/algorithms/micro/config.py` para defaults actuales.
