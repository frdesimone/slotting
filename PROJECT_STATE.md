# PROJECT_STATE — Slotting Escala

_Generado por nightly-audit. Última actualización: 2026-05-07_

---

## 1. Arquitectura general

Monorepo con dos apps:

- **`apps/slotting/`** — Backend Python/FastAPI. Pipeline de slotting logístico en dos fases (macro + micro). Expone API REST con Bearer auth.
- **`apps/slot-flow-pilot/`** — Frontend React/TypeScript/Vite (rama `main`). Wizard de 4 pasos: upload Excel → audit → macro slotting → micro slotting.

Branch de desarrollo del backend: `dev`.

---

## 2. Modelo de datos y configuración

### Entidades principales

| Clase | Campos clave |
|-------|-------------|
| `SKU` | `sku_id`, `rot`, `height`, `volume`, `weight`, `width`, `length`, `cycle_units`, `is_sensitive`, `vlm_eligible` |
| `Order` | `order_id`, `sku_ids: list[str]` |
| `AffinityGroup` | `sku_ids`, `score`, `seed_sku_id` |
| `StorageConfig` | `name`, `capacity_m3`, `constraints` |
| `Tray` / `TrayPlan` | resultado del bin-packing físico |

### Configuración

- `MacroSlottingConfig(storage_types: list[StorageConfig], abc_thresholds)` — nueva API (redesignada en ciclo anterior, reemplaza flags `vlm_eligible`/`is_sensitive`).
- `MicroSlottingConfig` — dataclass frozen con ~20 parámetros (cycle_days, group_max_size, tray_base_area_max, etc.).

---

## 3. Funcionalidades implementadas

- Carga de Excel con detección dinámica de cabecera (sheets "Base Cód." + "Pedidos").
- Carga legacy desde dos CSV separados (`load_slotting_inputs`).
- Fusión de filas duplicadas de SKU (campos complementarios en filas distintas).
- Derivación de volumen desde dimensiones físicas cuando el volumen no está explícito.
- Detección flexible de columna de cantidad (`"cantidad um de venta"` con fallback a `"cantidad*"`).
- Macro slotting: clasificación ABC + asignación a `StorageConfig` por constraints.
- Micro slotting completo: grafo afinidad Jaccard → seeds estratificados → crecimiento greedy → selección non-overlapping → subgrupos físicos → bin-packing en bandejas → optimización simulated annealing.
- Exportación CSV de bandejas.
- Detección de outliers y exclusión por tipo.
- Historial de ejecuciones en PostgreSQL (4 tablas: users, executions, macro_results, micro_results).

---

## 4. API

| Método | Ruta | Función |
|--------|------|---------|
| POST | `/api/v1/outliers` | Detectar anomalías (Excel + mapping) |
| POST | `/api/v1/macro` | Macro slotting → asignación a tipos de almacenamiento |
| POST | `/api/v1/micro` | Micro slotting → CSV de bandejas |
| POST | `/api/v1/template` | Generar Excel template vacío |
| GET | `/api/v1/history` | Historial de ejecuciones del usuario |
| GET | `/` | Health check |

Auth: HTTP Bearer token (`API_TOKEN` env var).

---

## 5. Frontend

Wizard de 4 pasos en React 18 + TypeScript + Vite + shadcn-ui:

1. **Step 1** — Upload Excel + mapeo de columnas
2. **Step 2** — Audit: outliers, exclusiones
3. **Step 3** — Macro: configurar tipos de almacenamiento → ejecutar
4. **Step 4** — Micro: configurar VLMs → ejecutar → descargar CSV

Estado global en `SlottingContext`. Mock engine en `slottingEngine.ts` para testing sin backend.

---

## 6. Decisiones técnicas relevantes

- **Macro API redesignada**: se eliminaron los flags `is_sensitive`/`vlm_eligible` como enrutamiento automático. Los tipos de almacenamiento ahora se definen como `StorageConfig` explícitos. 3 tests de la API anterior marcados como `xfail(strict=True)` hasta ser reescritos con la nueva API.
- **CSV loader refactorizado**: `_load_from_csv_generic` usa pipeline de dos pasos (parse → merge → derive) para evitar que volúmenes derivados de dimensiones sobreescriban valores explícitos en filas posteriores.
- **`load_slotting_inputs` corregida**: wrapper para dos CSV separados (legacy/test). Llama a los loaders directamente en lugar de delegar a `load_slotting_inputs_with_stats` (que espera un solo Excel).
- **DB opcional en scripts**: `run_micro_slotting.py` captura `OperationalError` de PostgreSQL y continúa sin persistir, para ejecutarse en entornos sin BD disponible.

---

## 7. Deuda técnica

- 3 tests macro (`test_api_macro_execution`, `test_macro_all_sensitive_rejected`, `test_macro_zero_capacity`) marcados `xfail` — deben reescribirse con `StorageConfig` explícitos.
- Emojis en prints del backend Excel (`_load_from_excel_bremen`, loader con_stats) pueden fallar en sistemas Windows con encoding cp1252 — pendiente limpieza.
- Frontend (`slot-flow-pilot`) no tiene cobertura de tests.

---

## 8. Proximos pasos

- Reescribir los 3 tests macro con la nueva API de `StorageConfig`.
- Limpiar emojis de todos los `print` del backend.
- Primera demo con Bremen sobre el CSV output.
- Evaluar deploy a DigitalOcean (backend) + Vercel (frontend).
