## Micro-slotting V1 (detalle)

Esta versión genera grupos lógicos por afinidad y luego selecciona un set
sin solapamientos (Paso 6). No incluye packing físico ni asignación a VLM.

### Paso 0 — Preparar datos base

- `rot`: rotación por líneas (cuántas veces aparece el SKU en órdenes).
- `height`, `volume`, `weight`.
- `cycle_units` se estima en el loader usando `cycle_days / period_days`.

### Paso 1 — Grafo de afinidades (co-ocurrencia)

1) Por orden, usar el set de SKUs (sin repetidos).
2) Contar `orders_with[i]` y `orders_with_both[i,j]`.
3) Afinidad V1: Jaccard = `both / (with_i + with_j - both)`.
4) Filtrar por `aff_min` y guardar top-K vecinos por SKU.

Resultado: grafo ralo con vecinos relevantes.

### Paso 2 — Seeds

- Seeds = top N SKUs por rotación (`seed_count`).

### Paso 3 — Score de grupo

`Score = wa * Affinity + wr * Rotation - wh * HeightPenalty`

- Afinidad V1: modelo estrella (seed vs cada miembro).
- Rotación: suma de `rot` del grupo.
- Penalización de altura: convexa según desperdicio (ver `group_score.py`).

### Paso 4 — Crecimiento greedy

Desde el seed, se intenta agregar candidatos (1-hop por default) que mejoren
el score. Se corta por:
- `min_delta` (si no mejora).
- `max_group_size`.

### Paso 5 — Un grupo por seed

Se genera un grupo por seed usando el greedy anterior.

### Paso 6 — Deduplicación y selección sin solapamientos

Implementado en `select_groups(...)`.

1) **Deduplicación por set de SKUs**
   - Se considera duplicado si tiene el mismo set de SKUs.
   - Se conserva el grupo con mayor `score` (tie-break: mayor rotación total).

2) **Densidad de valor**
   - `value_density = score / cost`.
   - `cost` por defecto: volumen por ciclo.
     - `cycle_units` si existe; fallback:
       `avg_units_per_line * rot`, y si no existe, `rot`.

3) **Selección greedy sin solapamiento**
   - Ordena por `density`, luego `score`, luego `rotation`.
   - Agrega solo si ningún SKU ya fue asignado.

Resultado: cada SKU aparece en **máximo un grupo**.
