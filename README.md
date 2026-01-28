
# slotting

Repo base para el proyecto de slotting.

## Setup

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

## Micro-slotting V1 (afinidades)

Entrada esperada (ya procesada, sin leer CSVs en esta etapa):
- `skus`: lista de `SKU` con `rot`, `height`, `volume`, `weight`
- `orders`: lista de `Order` con `sku_ids`

Ejemplo de uso:

```python
from slotting.algorithms.micro import MicroSlottingConfig, build_groups, load_micro_slotting_inputs

config = MicroSlottingConfig()
skus, orders = load_micro_slotting_inputs(
    codes_csv_path="docs/Base de códigos - semestre jun-nov  (11-1-2026) - Std Logix.xlsx - Base cód. segun pedidos-final.csv",
    orders_csv_path="docs/Base de pedidos - semestre jun-nov  (2-1-2026) - Std Logix.xlsx - Consolidado pedidos.csv",
    cycle_days=config.cycle_days,
    period_days=180.0,
)
groups = build_groups(skus=skus, orders=orders, config=config)
```

Notas:
- `rot` es por lineas (conteo de filas) y `cycle_units` se calcula como `sum(unidades) * (cycle_days / period_days)`.
- SKUs sin datos completos en el master se excluyen.

### Flujo de prep (resumen)

1) Cargar master de códigos y normalizar campos.
2) Cargar pedidos y contar `rot` (líneas) + `unidades`.
3) Calcular `cycle_units` y filtrar SKUs incompletos.
4) Filtrar pedidos vacíos tras el cruce con SKUs válidos.

### Limitaciones actuales

- Afinidades `O(n^2)` por pedido: órdenes muy grandes pueden tardar mucho.
- No hay salida física a bandejas; solo se generan grupos lógicos.
- SKUs sin altura/volumen/peso se excluyen del proceso.

### Ejecucion rapida con CSVs locales

```bash
python scripts/run_micro_slotting.py
```

Parametros utiles: `--cycle-days`, `--period-days`, `--seed-count`, `--top-k-neighbors`, `--aff-min`, `--max-group-size`.
- El output son `AffinityGroup` en memoria (aun sin salida fisica).
