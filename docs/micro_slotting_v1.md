## Micro-slotting V1 (detalle)

Esta versión genera grupos lógicos por afinidad y luego selecciona un set
sin solapamientos (Paso 6). No incluye packing físico ni asignación a VLM.

### Paso 0 — Preparar datos base

- `rot`: rotación por líneas (cuántas veces aparece el SKU en órdenes).
- `height`, `volume`, `weight`.
- `cycle_units` se estima en el loader usando `cycle_days / period_days` y se redondea hacia arriba
  (`ceil`) al momento de usarlo en costos y asignación física.

### Paso 1 — Grafo de afinidades (co-ocurrencia)

1) Por orden, usar el set de SKUs (sin repetidos).
2) Contar `orders_with[i]` y `orders_with_both[i,j]`.
3) Afinidad V1: Jaccard = `both / (with_i + with_j - both)`.
4) Filtrar por `graph_aff_min` y guardar top-K vecinos por SKU.

Resultado: grafo ralo con vecinos relevantes.

### Paso 2 — Seeds

- Seeds = N SKUs por rotación según estrategia (`group_seed_count`, `group_seed_strategy`).
- Default: estratificada 40/40/20 entre top/mid/tail.

### Paso 3 — Score de grupo

`Score = group_score_wa * Affinity + group_score_wr * Rotation - group_score_wh * HeightPenalty`

- Afinidad V1: par a par (full affinity) por default.
- Rotación: suma de `rot` del grupo.
- Penalización de altura: convexa y configurable según `max_height - avg_height_by_area`.
  - `avg_height_by_area = total_volume_mm3 / total_area_mm2`
  - `HeightPenalty = (diff / group_height_ref) ** group_height_p`

### Paso 4 — Crecimiento greedy

Desde el seed, se intenta agregar candidatos (1-hop por default) que mejoren
el score. Se corta por:
- `group_min_delta` (si no mejora).
- `group_max_size`.

### Paso 5 — Un grupo por seed

Se genera un grupo por seed usando el greedy anterior.

### Paso 6 — Deduplicación y selección sin solapamientos

Implementado en `select_groups(...)`.

1) **Deduplicación por set de SKUs**
   - Se considera duplicado si tiene el mismo set de SKUs.
   - Se conserva el grupo con mayor `score` (tie-break: mayor rotación total).

2) **Ranking de selección**
   - Por defecto: `score` puro (sin costo).
   - Opcional: `value_density = score / cost` si `selection_cost_mode=cycle_volume`.

3) **Selección greedy sin solapamiento**
   - Ordena por `density`, luego `score`, luego `rotation`.
   - Agrega solo si ningún SKU ya fue asignado.

Resultado: cada SKU aparece en **máximo un grupo**.

### Paso 7 — Subgrupos y bandejas físicas

**7A Subgrouping (lógico → subgrupos):**
- Se parte desde pares de SKUs con mayor afinidad.
- Se crece con greedy usando un score lógico:
  `Affinity - subgroup_height_weight * HeightPenalty - SizePenalty`,
  y un **costo físico marginal** simulado por bandejas.
  - `HeightPenalty` usa la misma lógica convexa que en grupos.
- Se aplica un máximo de SKUs por subgrupo y caps para performance.
- Si quedan SKUs sin pares, se asignan como singletons si no hay alternativa.

Costo físico marginal (simulado por bandejas):
- `tray_count` y `area_waste_ratio` por subgrupo candidato.
- Penalización:  
  `subgroup_marginal_tray_weight * tray_count + subgroup_marginal_area_waste_weight * area_waste_ratio`.

**7B Bandejas (subgrupo → bandejas):**
- Capacidad por área base (`mm²`) y peso (`kg`).
- `area_base = volume / height` (con `volume` en m³ y `height` en mm).
- Se calcula la cantidad de bandejas por ciclo y se distribuyen unidades.
  - La asignación física usa unidades enteras (se trunca por `floor` al llenar).
  - Si quedan unidades remanentes, se agregan bandejas hasta el límite global `max_trays`.
  - `max_trays` es global a todo el run (no por subgrupo).

**SKUs no seleccionados (opcional):**
- Si `unassigned_include=True`, se empaquetan por altura + afinidad,
  respetando capacidad y `unassigned_height_delta_max`.

### Tabla de parámetros (defaults)

| Parámetro | Default | Descripción |
|---|---:|---|
| `cycle_days` | 7.0 | Días por ciclo. |
| `graph_top_k_neighbors` | 50 | Vecinos máximos por SKU en el grafo. |
| `graph_aff_min` | 0.03 | Afinidad mínima para crear aristas. |
| `group_seed_count` | 500 | Cantidad de seeds para grupos lógicos. |
| `group_seed_strategy` | stratified_40_40_20 | Estrategia de seeds (top/mid/tail). |
| `selection_cost_mode` | none | Ranking de selección (score vs densidad). |
| `group_min_delta` | 0.0 | Mejora mínima para agregar un candidato. |
| `group_max_size` | 24 | Máximo de SKUs por grupo lógico. |
| `group_score_wa` | 0.75 | Peso de afinidad en el score. |
| `group_score_wr` | 0.1 | Peso de rotación en el score. |
| `group_score_wh` | 0.10 | Peso de penalización de altura. |
| `group_height_ref` | 25.0 | Referencia de altura (mm) para penalización convexa. |
| `group_height_p` | 2.0 | Exponente de penalización de altura. |
| `subgroup_max_size` | 14 | Máximo de SKUs por subgrupo. |
| `subgroup_size_gamma` | 0.03 | Coeficiente de penalización de tamaño. |
| `subgroup_size_p` | 2 | Exponente de penalización de tamaño. |
| `subgroup_height_weight` | 0.25 | Peso de penalización de altura (subgrupo). |
| `subgroup_seed_pairs_cap` | 20 | Pares semillas máximos por grupo. |
| `subgroup_candidate_eval_cap` | 10 | Candidatos evaluados por paso. |
| `subgroup_min_delta` | 0.0 | Mejora mínima para aceptar un candidato. |
| `subgroup_allow_singleton` | False | Permite subgrupos unitarios. |
| `subgroup_singleton_strategy` | min_loss | Estrategia para remanentes. |
| `subgroup_marginal_tray_weight` | 1.0 | Peso de cantidad de bandejas en costo marginal. |
| `subgroup_marginal_area_waste_weight` | 200.0 | Peso de waste en costo marginal. |
| `unassigned_height_delta_max` | 30.0 | Delta máx de altura en reempaque. |
| `unassigned_include` | True | Empaquetar SKUs fuera de Paso 6. |
| `tray_base_area_max` | 3,513,700.0 | Área base máxima por bandeja (mm²). |
| `tray_weight_max` | 750.0 | Peso máximo por bandeja (kg). |
| `tray_op_void` | 0.10 | Vacío operativo aplicado al área. |
| `max_trays` | 256 | Máximo global de bandejas físicas permitidas (no por subgrupo). |
| `optimizer_tray_count_weight` | 0.2 | Peso de cantidad de bandejas en KPI híbrido. |
| `optimizer_area_waste_weight` | 200.0 | Peso de waste en KPI híbrido. |

### Glosario de unidades

- `height`: mm  
- `volume`: m³  
- `area_base`: mm² (`volume` convertido a mm³ / `height`)  
- `weight`: kg  

### Optimización y swaps

La documentación de API, validación híbrida y uso standalone se movió a:
`docs/micro_optimizer_and_swaps.md`.
