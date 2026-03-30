import io
import math
import os
import shutil
import ipaddress
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
import json

import pandas as pd

from sqlalchemy.orm import Session

from pydantic import BaseModel, Field

from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Request, Form, Body
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware # IMPORTANTE: Agregar esta importación

from .config import get_settings
from .logging_config import configure_logging

# --- IMPORTACIONES DEL CORE DE SLOTTING ---
from slotting.algorithms.common.prep import load_slotting_inputs_with_stats
from slotting.algorithms.common.prep.outliers import detect_outliers
from slotting.algorithms.macro import MacroSlottingConfig, run_macro_slotting
from slotting.algorithms.micro.config import MicroSlottingConfig
from slotting.algorithms.micro.affinity_graph import build_affinity_graph
from slotting.algorithms.micro.grouping import build_groups
from slotting.algorithms.micro.selection import select_groups
from slotting.algorithms.micro.step7 import build_tray_plans
from slotting.algorithms.micro.kpi_state import build_hybrid_kpi_state
from slotting.algorithms.common.prep.loader import _filter_orders_by_skus
from slotting.algorithms.micro.optimization.optimizer import optimize, LocalSearchConfig
from slotting.algorithms.micro.group_score import estimate_cycle_units
from slotting.algorithms.micro.utils import sku_unit_area_mm2, tray_capacity
from slotting.models import Tray, TrayItem
from .db.database import engine, Base, get_db
from .db.repository import save_macro_execution, save_micro_execution, get_user_executions, get_macro_executions, get_micro_executions



# Esto le dice a SQLAlchemy: "Che, revisá si existen las tablas. Si no, crealas"
Base.metadata.create_all(bind=engine)

logger = logging.getLogger("slotting")

# ==========================================
# 1. CONFIGURACIÓN DE APP Y SEGURIDAD
# ==========================================
app = FastAPI(title="Slotting API", description="API para algoritmos de Macro y Micro Slotting")

# --- CONFIGURACIÓN DE CORS ---
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173") # O el puerto que use tu Vite/React local

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_TOKEN = os.environ.get("API_TOKEN", "token_desarrollo_local_123")
security = HTTPBearer()

def verificar_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.credentials != API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


# ==========================================
# MODELOS PYDANTIC PARA MICRO SLOTTING
# ==========================================
class StorageTypeConfig(BaseModel):
    storage_type: str
    max_trays: int
    max_weight: float
    tray_length: float
    tray_width: float
    is_fixed_height: bool = False
    is_multiproduct: bool | None = None
    stackability_factor: int | None = None
    # Paramétricos (opcionales; si faltan se derivan de tray_* y max_weight)
    max_w: float | None = None
    max_l: float | None = None
    max_weight_loc: float | None = None
    max_h_loc: float | None = None
    max_h_storage: float | None = None
    is_variable_height: bool | None = None
    enforce_integer_replenishment: bool = False
    round_to_one_threshold: float = 0.25


class SkuMicroInput(BaseModel):
    sku_id: str
    storage_type: str


class WeightsConfig(BaseModel):
    affinity: float
    rotation: float
    height: float


class MicroPayload(BaseModel):
    storages: list[StorageTypeConfig]
    sku_storage_mapping: dict[str, str] = Field(default_factory=dict)
    weights: WeightsConfig
    # Campos adicionales para compatibilidad con el flujo actual
    cycle_days: float = 15.0
    include_zero_rot: bool = False
    optimize_trays: bool = False
    opt_time_ms: int = 10000
    n_vlms: int = 10
    n_trays_per_vlm: int = 100
    mapping: dict | None = None
    period_days: float = 180.0
    vlm_skus_ids: list[str] | None = None  # Fallback: IDs directos si skus no tiene storage_type


# ==========================================
# 3. UTILIDADES
# ==========================================
def guardar_temp(upload_file: UploadFile) -> Path:
    temp_path = Path(f"/tmp/{upload_file.filename}")
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return temp_path

# ==========================================
# 4. ENDPOINTS REALES
# ==========================================

@app.get("/")
def read_root():
    return {"status": "ok", "message": "API de Slotting operativa."}


def _safe_json(val):
    """Parsea JSON si viene como string; si ya es dict/list, lo devuelve tal cual."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return None
    return val


@app.get("/api/v1/history")
def get_history(
    token: str = Depends(verificar_token),
    db: Session = Depends(get_db),
):
    """Retorna el historial de ejecuciones Macro y Micro del usuario."""
    CURRENT_USER_ID = "frontend_user_mock_123"

    macro_rows = get_macro_executions(db, CURRENT_USER_ID, limit=20)
    micro_rows = get_micro_executions(db, CURRENT_USER_ID, limit=20)

    macro_list = []
    for exec_obj, macro_res in macro_rows:
        macro_list.append({
            "execution_id": str(exec_obj.id),
            "created_at": exec_obj.created_at.isoformat() if exec_obj.created_at else None,
            "params": _safe_json(exec_obj.parameters),
            "kpi_results": {
                "total_skus": macro_res.total_skus,
                "vlm_skus_count": macro_res.vlm_skus_count,
                "rack_skus_count": macro_res.rack_skus_count,
                "vlm_fill_percentage": macro_res.vlm_fill_percentage,
            },
            "output_data": _safe_json(macro_res.skus_details),
        })

    micro_list = []
    for exec_obj, micro_res in micro_rows:
        micro_list.append({
            "execution_id": str(exec_obj.id),
            "created_at": exec_obj.created_at.isoformat() if exec_obj.created_at else None,
            "params": _safe_json(exec_obj.parameters),
            "kpi_results": {
                "total_trays": micro_res.total_trays,
                "avg_area_occupancy_pct": micro_res.avg_area_occupancy_pct,
                "optimized": micro_res.optimized,
            },
            "output_data": _safe_json(micro_res.trays_export),
        })

    return {"status": "success", "macro": macro_list, "micro": micro_list}


@app.post("/api/v1/outliers") # o /v1/outliers según como lo tengas
async def detectar_outliers_endpoint(
    file: UploadFile = File(...), # <-- AHORA ES UN SOLO ARCHIVO
    cycle_days: float = Form(15.0),
    outliers_config: str = Form("{}"),
    
    # --- Mapeo Dinámico ---
    sheet_maestro: str = Form("Base Cód."),
    col_sku_maestro: str = Form("Material"),
    col_volumen: str = Form("M3/UMB"),
    col_peso: str = Form("KG/UMB"),
    col_alto: str = Form("Alto"),
    col_ancho: str = Form("Ancho"),
    col_largo: str = Form("Largo"),
    col_desc: str = Form("Descripción"),
    col_cajas_m3: str = Form("Cajas/M3"),
    col_categoria: str = Form("Categoría"),
    sheet_pedidos: str = Form("Pedidos"),
    col_pedido_id: str = Form("Nro pedido"),
    col_pedido_sku: str = Form("Codigo II - Producto"),
    col_pedido_cant: str = Form("Cantidad UM de venta"),
    
    token: str = Depends(verificar_token)
):
    """Detecta y retorna anomalías en el dataset (Un solo archivo Excel)."""
    path_file = guardar_temp(file) # Guardamos el único Excel temporalmente
    
    try:
        mapping_config = {
            "sheet_maestro": sheet_maestro,
            "col_sku_maestro": col_sku_maestro,
            "col_volumen": col_volumen,
            "col_peso": col_peso,
            "col_alto": col_alto,
            "col_ancho": col_ancho,
            "col_largo": col_largo,
            "col_desc": col_desc,
            "col_cajas_m3": col_cajas_m3,
            "col_categoria": col_categoria,
            "sheet_pedidos": sheet_pedidos,
            "col_pedido_id": col_pedido_id,
            "col_pedido_sku": col_pedido_sku,
            "col_pedido_cant": col_pedido_cant
        }

        # Le pasamos el mismo path para todo
        skus_dict, orders, stats = load_slotting_inputs_with_stats(
            file_path=path_file, # <-- CAMBIO CLAVE
            cycle_days=cycle_days,
            include_zero_rot=True,
            mapping=mapping_config
        )
        skus_list = list(skus_dict.values()) if isinstance(skus_dict, dict) else skus_dict

        # --- Debug: auditar mapeo de columnas (primeros 5 SKUs) ---
        debug_skus = skus_list[:5]
        debug_list = [
            {
                "sku_id": getattr(s, "sku_id", None),
                "description": getattr(s, "description", None),
                "weight": getattr(s, "weight", None),
                "volume": getattr(s, "volume", None),
                "length": getattr(s, "length", None),
                "width": getattr(s, "width", None),
                "height": getattr(s, "height", None),
                "category": getattr(s, "category", None),
                "family": getattr(s, "family", None),
            }
            for s in debug_skus
        ]
        print("🔍 [Debug] Primeros 5 SKUs mapeados:")
        print(json.dumps(debug_list, indent=2, default=str))

        rules_list = []
        try:
            if outliers_config and outliers_config.strip():
                parsed = json.loads(outliers_config)
                rules_list = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            logger.warning(f"outliers_config inválido, usando defaults: {outliers_config}")

        report = detect_outliers(skus_list, orders, rules=rules_list)
        sku_by_id = {s.sku_id: s for s in skus_list}

        # --- CÁLCULO DE RESUMEN GENERAL ---
        total_skus = len(skus_list)
        total_pedidos = len(orders)
        order_stats = getattr(stats, "order_stats", None)
        total_lineas = int(order_stats.kept_rows) if order_stats else 0
        total_unidades = float(order_stats.total_units) if order_stats else 0.0

        # Capturamos la cantidad de días del período histórico (Ingreso de Datos, default 180)
        period_days = float(getattr(order_stats, "period_days", 180.0)) if order_stats else 180.0

        total_kg = 0.0
        total_m3 = 0.0

        # Iteramos UNA SOLA VEZ sobre el catálogo de SKUs únicos
        for sku_obj in skus_list:
            unit_weight = float(getattr(sku_obj, "weight", 0) or 0)
            vol_unit = float(getattr(sku_obj, "volume", 0) or getattr(sku_obj, "vol_unit", 0) or 0)
            units_sold = float(getattr(sku_obj, "units_sold_total", 0) or 0)

            if units_sold > 0:
                total_kg += units_sold * unit_weight
                total_m3 += units_sold * vol_unit

        lineas_por_pedido = total_lineas / total_pedidos if total_pedidos > 0 else 0.0

        summary_stats = {
            "total_skus": total_skus,
            "total_pedidos": total_pedidos,
            "total_orders": total_pedidos,
            "total_lineas": total_lineas,
            "total_lines": total_lineas,
            "total_unidades": int(total_unidades) if total_unidades == int(total_unidades) else round(total_unidades, 2),
            "total_units": int(total_unidades) if total_unidades == int(total_unidades) else round(total_unidades, 2),
            "total_kg": round(total_kg, 2),
            "total_m3": round(total_m3, 3),
            "period_days": period_days,
            "lineas_por_pedido": round(lineas_por_pedido, 2),
        }

        def sku_desc(sku) -> str:
            return (getattr(sku, "description", None) or "") if sku else ""

        # Enriquecer items con description cuando falte (para SKUs)
        categories = []
        for rule_id, data in report.items():
            target = data.get("target", "sku")
            name = data.get("name", rule_id)
            attribute = data.get("attribute", "")
            items = data.get("items", [])
            enriched = []
            for it in items:
                if "sku_id" in it and not it.get("description"):
                    sku = sku_by_id.get(it["sku_id"])
                    it = {**it, "description": sku_desc(sku)}
                enriched.append(it)
            categories.append({"id": rule_id, "name": name, "target": target, "attribute": attribute, "items": enriched})
        unique_categories = sorted({
            str(getattr(s, "category", "") or "").strip()
            for s in skus_list
            if str(getattr(s, "category", "") or "").strip()
        })
        response_data = {
            "status": "success",
            "summary": summary_stats,
            "categories": categories,
            "unique_categories": unique_categories,
            "validation": {
                "maestro": stats.maestro_validation.__dict__ if getattr(stats, "maestro_validation", None) else None,
                "pedidos": stats.pedidos_validation.__dict__ if getattr(stats, "pedidos_validation", None) else None,
            },
        }
        
        # Imprimir en los logs
        print(f"📤 [RESPONSE OUTLIERS]: {json.dumps(response_data, default=str)}")
        
        return response_data
    
    except Exception as e:
        logger.error(f"Error en outliers: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if path_file.exists(): path_file.unlink() # Borramos el temporal


@app.post("/api/v1/template")
def download_template(mapping: dict = Body(...)):
    """Genera un Excel vacío con las hojas y columnas según el mapeo actual."""
    sheet_maestro = mapping.get("sheet_maestro", "Base Cód.").strip() or "Base Cód."
    sheet_pedidos = mapping.get("sheet_pedidos", "Pedidos").strip() or "Pedidos"

    cols_maestro = [
        mapping.get("col_sku_maestro", "Material"),
        mapping.get("col_desc", "Descripción"),
        mapping.get("col_peso", "Peso (KG)"),
        mapping.get("col_alto", "Alto (CM)"),
        mapping.get("col_ancho", "Ancho (CM)"),
        mapping.get("col_largo", "Largo (CM)"),
        mapping.get("col_cajas_m3", "UM venta a UM reposición"),
        mapping.get("col_categoria", "Categoría"),
    ]

    cols_pedidos = [
        mapping.get("col_pedido_id", "Nro pedido"),
        mapping.get("col_pedido_sku", "Codigo II - Producto"),
        mapping.get("col_pedido_cant", "Cantidad UM de venta"),
        mapping.get("col_pedido_fecha", "Fecha"),
    ]

    cols_maestro = [c for c in cols_maestro if c and str(c).strip()]
    cols_pedidos = [c for c in cols_pedidos if c and str(c).strip()]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        pd.DataFrame(columns=cols_maestro).to_excel(writer, sheet_name=sheet_maestro, index=False)
        pd.DataFrame(columns=cols_pedidos).to_excel(writer, sheet_name=sheet_pedidos, index=False)
    output.seek(0)

    headers = {"Content-Disposition": 'attachment; filename="template_slotting.xlsx"'}
    return StreamingResponse(
        output,
        headers=headers,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.post("/api/v1/macro")
async def ejecutar_macro(
    file: UploadFile = File(...), 
    
    # --- NUEVOS CAMPOS ---
    exclude_outliers: bool = Form(False),
    include_zero_rot: bool = Form(True),
    excluded_skus: str = Form("[]"),
    excluded_orders: str = Form("[]"),
    storage_types: str = Form("[]"), # Array JSON de almacenamientos
    
    # --- Mapeo Dinámico ---
    sheet_maestro: str = Form("Base Cód."),
    col_sku_maestro: str = Form("Material"),
    col_volumen: str = Form("M3/UMB"),
    col_peso: str = Form("KG/UMB"),
    col_alto: str = Form("Alto"),
    col_ancho: str = Form("Ancho"),
    col_largo: str = Form("Largo"),
    col_desc: str = Form("Descripción"),
    col_cajas_m3: str = Form("Cajas/M3"),
    col_categoria: str = Form("Categoría"),
    sheet_pedidos: str = Form("Pedidos"),
    col_pedido_id: str = Form("Nro pedido"),
    col_pedido_sku: str = Form("Codigo II - Producto"),
    col_pedido_cant: str = Form("Cantidad UM de venta"),
    
    token: str = Depends(verificar_token),
    db: Session = Depends(get_db)
):
    path_file = guardar_temp(file)
    CURRENT_USER_ID = "frontend_user_mock_123"

    try:
        mapping_config = {
            "sheet_maestro": sheet_maestro, "col_sku_maestro": col_sku_maestro,
            "col_volumen": col_volumen, "col_peso": col_peso,
            "col_alto": col_alto, "col_ancho": col_ancho, "col_largo": col_largo,
            "col_desc": col_desc, "col_cajas_m3": col_cajas_m3, "col_categoria": col_categoria,
            "sheet_pedidos": sheet_pedidos, "col_pedido_id": col_pedido_id,
            "col_pedido_sku": col_pedido_sku, "col_pedido_cant": col_pedido_cant
        }

        # Parsear exclusiones
        ex_skus_set, ex_orders_set = set(), set()
        if exclude_outliers:
            ex_skus_set = set(json.loads(excluded_skus))
            ex_orders_set = set(json.loads(excluded_orders))
            
        # Parsear Storage Types (cycle_days ahora va dentro de cada storage type)
        st_list = json.loads(storage_types)
        if not st_list:  # Fallback de seguridad si mandan vacío
            st_list = [{"name": "VLM", "priority": 1, "cycle_days": 15.0, "max_volume": float('inf'), "max_weight": float('inf'), "capacity": 60.0, "occupancy": 0.85, "max_cycle_volume_limit": float('inf'), "allowed_categories": []}]

        # Normalizar allowed_categories: vacío = [] = "permitir todas"
        def _normalize_allowed_categories(raw):
            if raw is None or raw == "":
                return []
            if isinstance(raw, list):
                return [c.strip() for c in raw if c and str(c).strip()]
            if isinstance(raw, str):
                return [c.strip() for c in raw.split(",") if c.strip()]
            return []

        for st in st_list:
            if isinstance(st, dict):
                st["allowed_categories"] = _normalize_allowed_categories(st.get("allowed_categories", ""))

        cycle_days_for_loader = float(st_list[0].get("cycle_days", 15.0)) if st_list else 15.0

        skus_list, orders, stats = load_slotting_inputs_with_stats(
            file_path=path_file,
            cycle_days=cycle_days_for_loader,
            period_days=180.0,
            include_zero_rot=include_zero_rot,
            mapping=mapping_config,
            excluded_skus=ex_skus_set,     # Pasamos los SKUs malos
            excluded_orders=ex_orders_set  # Pasamos los pedidos malos
        )

        # --- Debug: auditar mapeo de columnas (primeros 5 SKUs) ---
        print("🔍 [Debug MACRO] Primeros 5 SKUs mapeados:")
        debug_skus = skus_list[:5]
        debug_list = [
            {
                "sku_id": getattr(sku, "sku_id", None),
                "description": getattr(sku, "description", None),
                "weight": getattr(sku, "weight", None),
                "volume": getattr(sku, "volume", None),
                "length": getattr(sku, "length", None),
                "width": getattr(sku, "width", None),
                "height": getattr(sku, "height", None),
                "category": getattr(sku, "category", None),
                "family": getattr(sku, "family", None),
            }
            for sku in debug_skus
        ]
        print(json.dumps(debug_list, indent=2, default=str))

        from slotting.models.storage import StorageConfig

        storage_configs = [StorageConfig.from_dict(st) for st in st_list]
        config = MacroSlottingConfig(storage_types=storage_configs, abc_thresholds=(0.80, 0.95))
        results = run_macro_slotting(skus_list, config)

        sku_by_id = {s.sku_id: s for s in skus_list}
        
        # --- ARMADO DINÁMICO DE KPIS ---
        kpi_dict = {
            "total_skus": len(results),
            "allocations": {}
        }
        
        vlm_skus_details = []
        for st in storage_configs:
            st_name = st.name
            st_results = [r for r in results if r.storage_type == st_name]
            st_vol_used = sum(getattr(r, "cycle_volume", 0) for r in st_results)
            st_target = st.effective_capacity_m3()
            st_weight_allocated = sum(getattr(r, "total_weight", 0) for r in st_results)
            fill_pct = (st_vol_used / st_target) * 100 if st_target > 0 else 0
            occupancy_pct_real = fill_pct
            
            kpi_dict["allocations"][st_name] = {
                "skus_count": len(st_results),
                "volume_used": round(st_vol_used, 2),
                "volume_target": round(st_target, 2),
                "fill_percentage": round(fill_pct, 1),
                "total_weight_allocated": round(st_weight_allocated, 2),
                "occupancy_pct_real": round(occupancy_pct_real, 1),
            }

            vlm_skus_details.extend(
                [
                    {
                        "sku_id": r.sku_id,
                        "storage_type": r.storage_type,
                        "vol_cycle": getattr(r, "cycle_volume", 0.0),
                        "abc_class": getattr(r, "abc_class", "N/A"),
                        "description": getattr(r, "description", "") or "",
                        "boxes_per_m3": getattr(r, "boxes_per_m3", 0.0) or 0.0,
                        "category": getattr(r, "category", "") or "",
                        "weight": getattr(sku_by_id.get(r.sku_id), "weight", None) or 0.0,
                        "height": getattr(r, "height", None) or getattr(sku_by_id.get(r.sku_id), "height", None),
                        "width": getattr(r, "width", None) or getattr(sku_by_id.get(r.sku_id), "width", None),
                        "length": getattr(r, "length", None) or getattr(sku_by_id.get(r.sku_id), "length", None),
                        "total_weight": getattr(r, "total_weight", 0) or 0,
                        "total_vol": getattr(r, "total_vol", 0) or 0,
                        "replenishment_units": getattr(r, "replenishment_units", 0) or 0,
                    }
                    for r in st_results
                ]
            )
            
        unassigned = [r for r in results if r.storage_type == "UNASSIGNED"]
        kpi_dict["unassigned_count"] = len(unassigned)
        vlm_skus_details.extend(
            [
                {
                    "sku_id": r.sku_id,
                    "storage_type": r.storage_type,
                    "vol_cycle": getattr(r, "cycle_volume", 0.0),
                    "abc_class": getattr(r, "abc_class", "N/A"),
                    "description": getattr(r, "description", "") or "",
                    "boxes_per_m3": getattr(r, "boxes_per_m3", 0.0) or 0.0,
                    "category": getattr(r, "category", "") or "",
                    "weight": getattr(sku_by_id.get(r.sku_id), "weight", None) or 0.0,
                    "height": getattr(r, "height", None) or getattr(sku_by_id.get(r.sku_id), "height", None),
                    "width": getattr(r, "width", None) or getattr(sku_by_id.get(r.sku_id), "width", None),
                    "length": getattr(r, "length", None) or getattr(sku_by_id.get(r.sku_id), "length", None),
                    "total_weight": getattr(r, "total_weight", 0) or 0,
                    "total_vol": getattr(r, "total_vol", 0) or 0,
                    "replenishment_units": getattr(r, "replenishment_units", 0) or 0,
                }
                for r in unassigned
            ]
        )

        params_dict = {"storage_types": [s.to_dict() for s in storage_configs]}
        exec_id = save_macro_execution(db, CURRENT_USER_ID, params_dict, kpi_dict, vlm_skus_details)

        response_data = {
            "status": "success", "execution_id": str(exec_id), 
            "kpi": kpi_dict, "macro_skus": vlm_skus_details
        }
        print(f"📤 [RESPONSE MACRO]: {json.dumps(response_data, default=str)}")
        return response_data
    
    except Exception as e:
        logger.error(f"Error en macro: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if path_file.exists(): path_file.unlink()


def _rescue_unassigned_skus(
    unassigned_sku_ids: list[str],
    final_trays: list,
    sku_by_id: dict[str, object],
    storage_cfg: object,
    config: MicroSlottingConfig,
    qty_limit: int,
) -> list[str]:
    """Pasada de rescate: meter SKUs huérfanos en bandejas existentes o nuevas,
    ignorando constraints de calidad (afinidad, height delta, score delta)
    y respetando solo constraints físicas (área, peso).
    Retorna la lista de SKUs que aún no pudieron ser colocados."""
    if not unassigned_sku_ids:
        return []

    still_unassigned = []
    print(f"      [Rescue Debug] {len(unassigned_sku_ids)} SKUs a rescatar, {len(final_trays)} trays existentes, qty_limit={qty_limit}")

    for sku_id in unassigned_sku_ids:
        sku = sku_by_id.get(str(sku_id).strip())
        if sku is None:
            print(f"      [Rescue FAIL] SKU {sku_id}: no encontrado en sku_by_id")
            still_unassigned.append(sku_id)
            continue

        # Calcular métricas físicas del SKU
        unit_area = sku_unit_area_mm2(sku)
        unit_weight = float(getattr(sku, "weight", 0) or 0)
        unit_volume = float(getattr(sku, "volume", 0) or 0)
        unit_height = float(getattr(sku, "height", 0) or 0)
        cycle_units = estimate_cycle_units(sku)
        if cycle_units <= 0:
            cycle_units = 1.0

        um_ratio = float(getattr(sku, "um_ratio", 1.0) or getattr(sku, "boxes_per_m3", 1.0) or 1.0)
        if getattr(config, "enforce_integer_replenishment", False) and um_ratio > 0:
            repl = cycle_units / um_ratio
            if repl < 1.0:
                cycle_units = um_ratio if repl >= getattr(config, "round_to_one_threshold", 0.25) else um_ratio
            else:
                cycle_units = round(repl) * um_ratio

        # Calcular área y peso con apilamiento
        max_h_loc_cm = config.max_h_loc * 100.0 if config.max_h_loc > 0 else float("inf")
        max_h_storage_cm = config.max_h_storage * 100.0 if config.max_h_storage > 0 else float("inf")
        if config.is_variable_height:
            h_limit = unit_height
            if max_h_storage_cm < float("inf"):
                h_limit = min(h_limit, max_h_storage_cm)
        else:
            h_limit = max_h_loc_cm
        max_vertical = int(h_limit // unit_height) if unit_height > 0 else 1
        if max_vertical < 1:
            max_vertical = 1
        actual_stack = min(config.stackability_factor, max_vertical)

        stacks_needed = math.ceil(cycle_units / actual_stack) if actual_stack > 0 else cycle_units
        total_area_needed = stacks_needed * unit_area
        total_weight_needed = cycle_units * unit_weight

        placed = False

        # Intento 1: meter en una ubicación existente que tenga espacio
        best_avail_area = 0.0
        best_avail_weight = 0.0
        _is_mono = not getattr(config, "is_multiproduct", True)
        for tray in final_trays:
            # Monoproducto: solo cabe en ubicaciones vacías o que ya tengan este mismo SKU
            if _is_mono:
                _tray_sku_ids = {str(getattr(_i, "sku_id", "")).strip() for _i in getattr(tray, "items", [])}
                if _tray_sku_ids and _tray_sku_ids != {str(sku_id).strip()}:
                    continue
            tray_max_a = getattr(tray, "max_surface", None) or getattr(tray, "max_area", None)
            tray_max_a = float(tray_max_a) if tray_max_a is not None else float("inf")
            tray_max_w = getattr(tray, "max_weight", float("inf")) or float("inf")

            available_area = tray_max_a - getattr(tray, "area_used", 0)
            available_weight = tray_max_w - getattr(tray, "weight_used", 0)
            best_avail_area = max(best_avail_area, available_area)
            best_avail_weight = max(best_avail_weight, available_weight)

            if total_area_needed <= available_area and total_weight_needed <= available_weight:
                tray.items.append(TrayItem(
                    sku_id=sku_id,
                    units=cycle_units,
                    unit_volume=unit_volume,
                    unit_weight=unit_weight,
                    total_volume=cycle_units * unit_volume,
                    total_weight=total_weight_needed,
                    unit_area=unit_area,
                    total_area=total_area_needed,
                ))
                tray.area_used += total_area_needed
                tray.weight_used += total_weight_needed
                tray.height = max(getattr(tray, "height", 0) or 0, unit_height)
                placed = True
                print(f"      [Rescue OK] SKU {sku_id}: colocado en tray existente ({getattr(tray, 'tray_id', '?')})")
                break

        # Intento 2: crear una ubicación nueva si hay espacio de qty_limit
        if not placed and len(final_trays) < qty_limit:
            max_area, max_weight_tray = tray_capacity(
                config.tray_base_area_max, config.tray_op_void, config.tray_weight_max
            )
            if total_area_needed <= max_area and total_weight_needed <= max_weight_tray:
                new_tray = Tray(
                    tray_id=f"rescue-{sku_id}",
                    group_id="rescue",
                    subgroup_id="rescue",
                    height=unit_height,
                    max_area=max_area,
                    max_weight=max_weight_tray,
                    area_used=total_area_needed,
                    weight_used=total_weight_needed,
                    items=[TrayItem(
                        sku_id=sku_id,
                        units=cycle_units,
                        unit_volume=unit_volume,
                        unit_weight=unit_weight,
                        total_volume=cycle_units * unit_volume,
                        total_weight=total_weight_needed,
                        unit_area=unit_area,
                        total_area=total_area_needed,
                    )],
                )
                final_trays.append(new_tray)
                placed = True
                print(f"      [Rescue OK] SKU {sku_id}: nueva ubicación creada (rescue-{sku_id})")
            else:
                print(f"      [Rescue FAIL] SKU {sku_id}: no cabe en tray nueva. area_needed={total_area_needed:.0f} vs max={max_area:.0f}, weight_needed={total_weight_needed:.1f} vs max={max_weight_tray:.1f}")
        elif not placed:
            print(f"      [Rescue FAIL] SKU {sku_id}: no cabe en existentes (best_avail: area={best_avail_area:.0f} vs needed={total_area_needed:.0f}, weight={best_avail_weight:.1f} vs needed={total_weight_needed:.1f}) y qty_limit alcanzado ({len(final_trays)}>={qty_limit})")

        if not placed:
            still_unassigned.append(sku_id)

    return still_unassigned


@app.post("/api/v1/micro")
async def ejecutar_micro(
    file: UploadFile = File(...),
    payload: str = Form(..., description="JSON con MicroPayload: storages, skus, weights, mapping, etc."),
    token: str = Depends(verificar_token),
    db: Session = Depends(get_db)
):
    """Ejecuta el Micro Slotting (Armado de Bandejas), opcionalmente optimizado."""
    try:
        payload_data = MicroPayload.model_validate(json.loads(payload))
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=f"Payload JSON inválido: {e}") from e

    path_file = guardar_temp(file)
    CURRENT_USER_ID = "frontend_user_mock_123"
    
    try:
        mapping_config = payload_data.mapping or {}
        # Valores por defecto si mapping está vacío
        defaults = {
            "sheet_maestro": "Base Cód.",
            "col_sku_maestro": "Material",
            "col_volumen": "M3/UMB",
            "col_peso": "KG/UMB",
            "col_alto": "Alto",
            "col_ancho": "Ancho",
            "col_largo": "Largo",
            "col_desc": "Descripción",
            "col_cajas_m3": "Cajas/M3",
            "col_categoria": "Categoría",
            "sheet_pedidos": "Pedidos",
            "col_pedido_id": "Nro pedido",
            "col_pedido_sku": "Codigo II - Producto",
            "col_pedido_cant": "Cantidad UM de venta",
        }
        for k, v in defaults.items():
            if k not in mapping_config:
                mapping_config[k] = v
        if "period_days" not in mapping_config:
            mapping_config["period_days"] = payload_data.period_days

        # Mapa sku_id -> storage_type desde el payload optimizado
        sku_to_storage = {str(k).strip(): str(v).strip() for k, v in payload_data.sku_storage_mapping.items()}

        skus_list, orders, stats = load_slotting_inputs_with_stats(
            file_path=path_file,
            cycle_days=payload_data.cycle_days,
            period_days=payload_data.period_days,
            include_zero_rot=payload_data.include_zero_rot,
            mapping=mapping_config,
            excluded_skus=None
        )

        # Filtrar SKUs: solo los que están en payload.skus (respeta storage_type del usuario)
        sku_ids_in_payload = set(sku_to_storage.keys())
        skus_list = [s for s in skus_list if str(s.sku_id).strip() in sku_ids_in_payload]
        orders = _filter_orders_by_skus(orders, skus_list, stats)
        sku_by_id = {str(s.sku_id).strip(): s for s in skus_list}

        # Precomputar cantidad de pedidos por SKU (para detalles de no-asignados)
        orders_per_sku: dict[str, int] = {}
        for _ord in orders:
            for _sid in _ord.sku_ids:
                _s = str(_sid).strip()
                orders_per_sku[_s] = orders_per_sku.get(_s, 0) + 1

        print(f"🚀 [Micro] {len(skus_list)} SKUs cargados, {len(payload_data.storages)} tipos de almacenamiento.")

        def get_occ(t):
            return t.occupancy_percent if hasattr(t, 'occupancy_percent') else (getattr(t, 'area_used', 0) / getattr(t, 'max_area', 1)) * 100

        results_by_storage: dict[str, dict] = {}

        for storage_cfg in payload_data.storages:
            st_key = storage_cfg.storage_type.strip()
            st_upper = st_key.upper()

            # Filtrar SKUs que pertenecen a este storage_type
            skus_for_storage = [s for s in skus_list if sku_to_storage.get(str(s.sku_id).strip(), "").upper() == st_upper]
            if not skus_for_storage:
                print(f"   ⏭️ [Micro] {st_key}: sin SKUs, omitiendo.")
                continue

            orders_for_storage = _filter_orders_by_skus(orders, skus_for_storage, stats)

            # Altura fija: si is_fixed_height, peso 0; si no, usar payload.weights.height
            weight_height = 0.0 if storage_cfg.is_fixed_height else payload_data.weights.height

            # Config desde storage_cfg
            tray_area_mm2 = storage_cfg.tray_length * storage_cfg.tray_width * 1e6  # m² -> mm²
            # Límite holgado para permitir expansión y compresión sin explotar la RAM
            real_qty = int(storage_cfg.qty) if getattr(storage_cfg, "qty", None) is not None else int(getattr(storage_cfg, "max_trays", 64) or 64)
            safe_virtual_limit = max(100, real_qty * 3)
            config = MicroSlottingConfig(
                cycle_days=payload_data.cycle_days,
                max_trays=safe_virtual_limit,
                tray_weight_max=storage_cfg.max_weight,
                tray_base_area_max=tray_area_mm2,
                group_score_wa=payload_data.weights.affinity,
                group_score_wr=payload_data.weights.rotation,
                group_score_wh=weight_height,
                is_multiproduct=storage_cfg.is_multiproduct if storage_cfg.is_multiproduct is not None else True,
                stackability_factor=storage_cfg.stackability_factor if storage_cfg.stackability_factor is not None else 1,
                is_variable_height=storage_cfg.is_variable_height if storage_cfg.is_variable_height is not None else False,
                max_h_loc=storage_cfg.max_h_loc if storage_cfg.max_h_loc is not None else 0.5,
                max_h_storage=storage_cfg.max_h_storage if storage_cfg.max_h_storage is not None else 5.0,
                group_max_size=20,
                subgroup_max_size=20,
                group_min_delta=0.0,
                subgroup_min_delta=0.0,
                enforce_integer_replenishment=getattr(storage_cfg, "enforce_integer_replenishment", False),
                round_to_one_threshold=getattr(storage_cfg, "round_to_one_threshold", 0.25),
            )

            # Ejecutar motor Micro
            affinity_graph = build_affinity_graph(orders=orders_for_storage, top_k=config.graph_top_k_neighbors, aff_min=config.graph_aff_min, metric=config.affinity_metric)
            groups = build_groups(skus=skus_for_storage, orders=orders_for_storage, config=config)
            selected_groups = select_groups(groups=groups, skus=skus_for_storage, selection_cost_mode=config.selection_cost_mode)
            tray_plans = build_tray_plans(selected_groups=selected_groups, skus=skus_for_storage, affinity_graph=affinity_graph, config=config)
            final_trays = [tray for plan in tray_plans for tray in plan.trays]

            if payload_data.optimize_trays and final_trays:
                sg_by_id = {sg.subgroup_id: sg for plan in tray_plans for sg in plan.subgroups}
                sku_by_id_local = {s.sku_id: s for s in skus_for_storage}
                hybrid = build_hybrid_kpi_state(
                    subgroups=list(sg_by_id.values()),
                    trays=final_trays,
                    sku_by_id=sku_by_id_local,
                    affinity_graph=affinity_graph,
                    config=config,
                )
                opt_config = LocalSearchConfig(time_budget_ms=payload_data.opt_time_ms, allow_annealing=True)
                optimize(hybrid, opt_config)
                final_trays = hybrid.all_trays()

            # --- COMPRESOR DE BANDEJAS (FUSIONA GRUPOS) ---
            if getattr(storage_cfg, "is_multiproduct", True):
                compacted_trays = []

                def calc_tray_metrics(items, st_cfg, sku_dict):
                    # Agrupar SKUs idénticos para optimizar apilamiento
                    grouped = {}
                    for i in items:
                        if i.sku_id in grouped:
                            grouped[i.sku_id] += getattr(i, "units", 0)
                        else:
                            grouped[i.sku_id] = getattr(i, "units", 0)

                    total_area = 0.0
                    total_weight = 0.0
                    max_h_m = st_cfg.max_h_loc if st_cfg.max_h_loc is not None else 0.5
                    max_h_storage_m = st_cfg.max_h_storage if st_cfg.max_h_storage is not None else 5.0
                    is_var_h = st_cfg.is_variable_height if st_cfg.is_variable_height is not None else False
                    sf = st_cfg.stackability_factor if st_cfg.stackability_factor is not None else 1

                    current_max_h = 0.0
                    if is_var_h:
                        for s_id in grouped.keys():
                            obj = sku_dict.get(str(s_id).strip())
                            if obj:
                                current_max_h = max(current_max_h, float(obj.height or 0) / 100.0)
                    for s_id, units in grouped.items():
                        obj = sku_dict.get(str(s_id).strip())
                        if not obj:
                            continue
                        uh = float(obj.height or 0) / 100.0
                        uw = float(obj.width or 0) / 100.0
                        ul = float(obj.length or 0) / 100.0
                        uwgt = float(getattr(obj, "weight", 0) or 0)

                        if is_var_h:
                            h_limit = max(current_max_h, uh)
                            if max_h_storage_m > 0:
                                h_limit = min(h_limit, max_h_storage_m)
                        else:
                            h_limit = max_h_m

                        mv = int(h_limit // uh) if uh > 0 else 1
                        if mv < 1:
                            mv = 1
                        astack = min(sf, mv)

                        stks = math.ceil(units / astack) if astack > 0 else units
                        total_area += (uw * ul * 1e6) * stks
                        total_weight += units * uwgt

                    return total_area, total_weight

                for t in final_trays:
                    t_items = getattr(t, "items", [])
                    if not t_items:
                        continue
                    merged = False
                    for ct in compacted_trays:
                        # Simular la física de mezclar ambas bandejas
                        combined_items = ct.items + t_items
                        new_area, new_weight = calc_tray_metrics(combined_items, storage_cfg, sku_by_id)

                        ct_max_w = getattr(ct, "max_weight", float("inf")) or float("inf")
                        # Corrección: max_surface (export) o max_area (modelo Tray) para evitar área infinita
                        ct_max_a = getattr(ct, "max_surface", None) or getattr(ct, "max_area", None)
                        ct_max_a = float(ct_max_a) if ct_max_a is not None else float("inf")

                        if new_weight <= ct_max_w and new_area <= ct_max_a:
                            # Se aprueba la fusión: entra perfecto
                            ct.items = combined_items
                            ct.weight_used = new_weight
                            ct.area_used = new_area
                            ct.height = max(getattr(ct, "height", 0) or 0, getattr(t, "height", 0) or 0)
                            merged = True
                            break
                    if not merged:
                        # No entra, queda como bandeja independiente con sus métricas limpias
                        new_area, new_weight = calc_tray_metrics(t_items, storage_cfg, sku_by_id)
                        t.area_used = new_area
                        t.weight_used = new_weight
                        compacted_trays.append(t)
                final_trays = compacted_trays

            # --- CORTE FINAL POR CAPACIDAD FÍSICA REAL ---
            _raw_qty = getattr(storage_cfg, "qty", None) or getattr(storage_cfg, "max_trays", None)
            qty_limit = int(_raw_qty) if (_raw_qty is not None and int(_raw_qty) > 0) else 999999
            if len(final_trays) > qty_limit:
                print(f"⚠️ Recortando de {len(final_trays)} a {qty_limit} ubicaciones en {st_key}")
                final_trays = final_trays[:qty_limit]

            skus_for_storage_ids = {str(s.sku_id).strip() for s in skus_for_storage}
            placed_skus_in_storage = set()
            for t in final_trays:
                for i in getattr(t, "items", []):
                    placed_skus_in_storage.add(str(getattr(i, "sku_id", "")).strip())
            unassigned_skus = list(skus_for_storage_ids - placed_skus_in_storage)

            # --- RESCATE: forzar SKUs huérfanos en bandejas (solo constraints físicas) ---
            if unassigned_skus:
                print(f"   🔄 [Rescue] {st_key}: intentando rescatar {len(unassigned_skus)} SKUs no asignados...")
                # Respetar el límite físico real. Si el pipeline llenó todas las ubicaciones,
                # rescue intenta meter SKUs en las existentes (pueden tener espacio libre).
                # Si no caben, cascadean al siguiente storage. No se crean ubicaciones fantasma.
                rescue_qty_limit = qty_limit
                unassigned_skus = _rescue_unassigned_skus(
                    unassigned_sku_ids=unassigned_skus,
                    final_trays=final_trays,
                    sku_by_id=sku_by_id,
                    storage_cfg=storage_cfg,
                    config=config,
                    qty_limit=rescue_qty_limit,
                )
                # Recalcular placed después del rescate
                prev_placed = len(placed_skus_in_storage)
                placed_skus_in_storage = set()
                for t in final_trays:
                    for i in getattr(t, "items", []):
                        placed_skus_in_storage.add(str(getattr(i, "sku_id", "")).strip())
                rescued_count = len(placed_skus_in_storage) - prev_placed
                print(f"   ✅ [Rescue] {st_key}: {rescued_count} SKUs rescatados, {len(unassigned_skus)} siguen sin asignar")

            # --- Detalles de SKUs no asignados (para diagnóstico en frontend) ---
            _max_tray_area, _max_tray_weight = tray_capacity(config.tray_base_area_max, config.tray_op_void, config.tray_weight_max)
            unassigned_skus_details = []
            for _uid in unassigned_skus:
                _uobj = sku_by_id.get(str(_uid).strip())
                if not _uobj:
                    unassigned_skus_details.append({"sku_id": _uid, "reason": "SKU no encontrado en datos"})
                    continue
                _cu = estimate_cycle_units(_uobj)
                _ua = sku_unit_area_mm2(_uobj)
                _uw = float(getattr(_uobj, "weight", 0) or 0)
                _stacks = max(1, math.ceil(_cu / max(1, config.stackability_factor)))
                _area_needed = _stacks * _ua
                _weight_needed = _cu * _uw
                if _area_needed > _max_tray_area:
                    _reason = f"Área de ciclo ({_area_needed/1e6:.3f} m²) supera capacidad de ubicación ({_max_tray_area/1e6:.3f} m²)"
                elif _weight_needed > _max_tray_weight:
                    _reason = f"Peso de ciclo ({_weight_needed:.1f} kg) supera límite ({_max_tray_weight:.1f} kg)"
                else:
                    _reason = "Sin espacio disponible (ubicaciones llenas o límite de capacidad alcanzado)"
                unassigned_skus_details.append({
                    "sku_id": _uid,
                    "description": getattr(_uobj, "description", ""),
                    "rotation": round(float(getattr(_uobj, "rot", 0) or 0), 4),
                    "height_cm": round(float(getattr(_uobj, "height", 0) or 0), 2),
                    "width_cm": round(float(getattr(_uobj, "width", 0) or 0), 2),
                    "length_cm": round(float(getattr(_uobj, "length", 0) or 0), 2),
                    "weight_kg": round(float(getattr(_uobj, "weight", 0) or 0), 2),
                    "volume_m3": round(float(getattr(_uobj, "volume", 0) or 0), 4),
                    "cycle_units": round(_cu, 2),
                    "cycle_volume_m3": round(_cu * float(getattr(_uobj, "volume", 0) or 0), 4),
                    "orders_count": orders_per_sku.get(str(_uid).strip(), 0),
                    "reason": _reason,
                })

            if not final_trays:
                results_by_storage[st_key] = {
                    "kpi": {"total_trays": 0, "total_locations": 0, "skus_placed": 0, "avg_area_occupancy_pct": 0, "optimized": payload_data.optimize_trays, "total_wasted_vol": 0},
                    "best_trays": [],
                    "locations": [],
                    "unassigned_skus": unassigned_skus,
                    "unassigned_skus_details": unassigned_skus_details,
                }
                continue

            total_trays = len(final_trays)
            avg_occupancy = sum(get_occ(t) for t in final_trays) / total_trays if total_trays else 0

            skus_dict = {str(s.sku_id).strip(): s for s in skus_list}
            total_wasted_volume = 0.0

            # Límites de la ubicación desde storage_cfg
            max_w = storage_cfg.max_w if storage_cfg.max_w is not None else storage_cfg.tray_width
            max_l = storage_cfg.max_l if storage_cfg.max_l is not None else storage_cfg.tray_length
            max_weight = storage_cfg.max_weight_loc if storage_cfg.max_weight_loc is not None else storage_cfg.max_weight
            is_var_h = storage_cfg.is_variable_height if storage_cfg.is_variable_height is not None else (not storage_cfg.is_fixed_height)
            max_h_loc = storage_cfg.max_h_loc if storage_cfg.max_h_loc is not None else 0.5
            max_h_storage = storage_cfg.max_h_storage if storage_cfg.max_h_storage is not None else 5.0

            max_surface = max_w * max_l
            max_volume = max_surface * (max_h_storage if is_var_h else max_h_loc)

            # Pre-computar días de inventario por SKU (para incluir en cada item del export)
            _stored_units_by_sku: dict[str, float] = {}
            for _t in final_trays:
                for _item in getattr(_t, "items", []):
                    _sid = str(getattr(_item, "sku_id", "")).strip()
                    _stored_units_by_sku[_sid] = _stored_units_by_sku.get(_sid, 0.0) + getattr(_item, "units", 0.0)
            _period = payload_data.period_days or 180.0
            inv_days_by_sku: dict[str, float] = {}
            for _sid, _su in _stored_units_by_sku.items():
                _sobj = skus_dict.get(_sid)
                if not _sobj:
                    continue
                _dd = _sobj.units_sold_total / _period if _period > 0 else 0.0
                if _dd > 0:
                    inv_days_by_sku[_sid] = round(min(_su / _dd, _period), 1)

            locations_export = []
            _loc_counter = 1
            for t in sorted(final_trays, key=lambda x: get_occ(x), reverse=True):
                clean_tray_id = f"{st_key}-{_loc_counter}"
                _loc_counter += 1
                items_export = []
                for i in t.items:
                    vol = getattr(i, "total_volume", 0) or 0
                    sku_obj = skus_dict.get(str(getattr(i, "sku_id", "")).strip())
                    desc = getattr(sku_obj, "description", "") if sku_obj else ""

                    um_ratio = getattr(sku_obj, "boxes_per_m3", None) or getattr(sku_obj, "um_ratio", 1.0)
                    try:
                        um_ratio = float(um_ratio)
                        if um_ratio <= 0: um_ratio = 1.0
                    except (ValueError, TypeError):
                        um_ratio = 1.0

                    # Tomar las unidades de venta directamente de la asignación del algoritmo
                    unidades_venta = getattr(i, "units", 0.0)
                    boxes = unidades_venta / um_ratio

                    items_export.append({
                        "sku": getattr(i, "sku_id", ""),
                        "vol": vol,
                        "description": desc,
                        "boxes": boxes,
                        "units": unidades_venta
                    })

                consolidated_items = {}
                for item in items_export:
                    sku_id = item.get("sku")
                    if not sku_id:
                        continue
                    sku_obj = skus_dict.get(str(sku_id).strip())
                    height = sku_obj.height if sku_obj else 0.0

                    if sku_id in consolidated_items:
                        consolidated_items[sku_id]["vol"] += item.get("vol", 0.0)
                        consolidated_items[sku_id]["boxes"] = consolidated_items[sku_id].get("boxes", 0.0) + item.get("boxes", 0.0)
                        consolidated_items[sku_id]["units"] = consolidated_items[sku_id].get("units", 0.0) + item.get("units", 0.0)
                    else:
                        consolidated_items[sku_id] = dict(item)
                        consolidated_items[sku_id]["height"] = height
                final_items = list(consolidated_items.values())

                tray_max_height = max([i.get("height", 0.0) for i in final_items], default=0.0)
                location_weight = 0.0
                location_surface = 0.0
                location_volume = 0.0
                location_items = []
                for item in final_items:
                    sku_id = item.get("sku")
                    sku_obj = skus_dict.get(str(sku_id).strip()) if sku_id else None
                    if not sku_obj:
                        continue

                    qty_boxes = item.get("boxes", 0.0)
                    qty_units = item.get("units", 0.0)  # Variable real para la física

                    unit_w = (float(sku_obj.width or 0) / 100.0)
                    unit_l = (float(sku_obj.length or 0) / 100.0)
                    unit_h = (float(sku_obj.height or 0) / 100.0)
                    unit_weight = float(getattr(sku_obj, "weight", 0) or 0)

                    is_var_h = storage_cfg.is_variable_height if storage_cfg.is_variable_height is not None else False
                    max_h_loc = storage_cfg.max_h_loc if storage_cfg.max_h_loc is not None else 0.5
                    max_h_storage = storage_cfg.max_h_storage if storage_cfg.max_h_storage is not None else 5.0
                    stack_factor = storage_cfg.stackability_factor if storage_cfg.stackability_factor is not None else 1

                    if is_var_h:
                        sku_heights = []
                        for i in final_items:
                            obj = skus_dict.get(str(i.get("sku")).strip()) if i.get("sku") else None
                            if obj is not None:
                                sku_heights.append(getattr(obj, "height", 0.0) or 0.0)
                        current_max_h = max(sku_heights, default=0.0) / 100.0
                        h_limit = max(current_max_h, unit_h)
                        if max_h_storage > 0:
                            h_limit = min(h_limit, max_h_storage)
                    else:
                        h_limit = max_h_loc

                    max_vertical = int(h_limit // unit_h) if unit_h > 0 else 1
                    if max_vertical < 1:
                        max_vertical = 1
                    actual_stack = min(stack_factor, max_vertical)

                    # Las pilas, área y peso se basan en UNIDADES DE VENTA, no en cajas
                    stacks_needed = math.ceil(qty_units / actual_stack) if actual_stack > 0 else qty_units

                    item_surface = (unit_w * unit_l) * stacks_needed
                    item_vol = item.get("vol", (unit_w * unit_l * unit_h) * qty_units)
                    item_total_weight = unit_weight * qty_units

                    location_weight += item_total_weight
                    location_surface += item_surface
                    location_volume += item_vol

                    location_items.append({
                        "sku": sku_id,
                        "description": item.get("description", ""),
                        "weight": round(item_total_weight, 2),
                        "surface": round(item_surface, 4),
                        "volume": round(item_vol, 4),
                        "replenishment_units": round(qty_boxes, 2),  # Al usuario le mostramos cajas
                        "rotation": round(float(getattr(sku_obj, "rot", 0) or 0), 4),
                        "inv_days": inv_days_by_sku.get(str(sku_id).strip(), 0.0),
                    })

                # Aire desperdiciado: usar altura real de los items (no la max del storage)
                if is_var_h:
                    # Altura variable: el aire se mide contra la altura real del SKU más alto en esta bandeja
                    effective_h_m = (tray_max_height / 100.0) if tray_max_height > 0 else max_h_loc
                else:
                    effective_h_m = max_h_loc
                if effective_h_m <= 0:
                    effective_h_m = 0.5
                total_tray_vol = effective_h_m * max_surface
                tray_wasted_vol = max(0.0, total_tray_vol - location_volume)
                total_wasted_volume += tray_wasted_vol

                _avg_rot = round(sum(li.get("rotation", 0) for li in location_items) / len(location_items), 4) if location_items else 0.0
                locations_export.append({
                    "location_id": clean_tray_id,
                    "occupancy_pct": round(get_occ(t), 2),
                    "max_height": tray_max_height,
                    "wasted_vol": tray_wasted_vol,
                    "sku_count": len(location_items),
                    "avg_rotation": _avg_rot,
                    "metrics": {
                        "used_weight": round(location_weight, 2),
                        "max_weight": round(max_weight, 2),
                        "used_surface": round(location_surface, 4),
                        "max_surface": round(max_surface, 4),
                        "used_volume": round(location_volume, 4),
                        "max_volume": round(max_volume, 4),
                    },
                    "items": location_items,
                })

            # --- KPI: Pedidos satisfechos por este storage ---
            # De TODOS los pedidos, cuántos tienen TODOS sus SKUs colocados en este storage.
            # Usa la lista completa de pedidos (orders), no la filtrada por storage.
            orders_satisfied = 0
            total_orders = len(orders)
            for order in orders:
                order_sku_set = {str(s).strip() for s in order.sku_ids}
                if order_sku_set and order_sku_set.issubset(placed_skus_in_storage):
                    orders_satisfied += 1
            orders_satisfied_pct = round((orders_satisfied / total_orders * 100), 2) if total_orders > 0 else 0.0

            # --- KPI: Días de inventario promedio (ponderado por demanda) ---
            # Consolidar unidades por SKU (puede estar en múltiples trays por splitting)
            stored_units_by_sku: dict[str, float] = {}
            for t in final_trays:
                for item in getattr(t, "items", []):
                    sid = str(getattr(item, "sku_id", "")).strip()
                    stored_units_by_sku[sid] = stored_units_by_sku.get(sid, 0.0) + getattr(item, "units", 0.0)
            # Promedio ponderado: cada SKU pesa según su demanda diaria
            # Esto evita que SKUs de demanda ínfima (ceileados a 1) inflen el promedio
            period_days = payload_data.period_days or 180.0
            weighted_days_sum = 0.0
            total_daily_demand = 0.0
            for sid, stored_units in stored_units_by_sku.items():
                sku_obj = skus_dict.get(sid)
                if not sku_obj:
                    continue
                daily_demand = sku_obj.units_sold_total / period_days if period_days > 0 else 0.0
                if daily_demand > 0:
                    inv_days = min(stored_units / daily_demand, period_days)  # Capear al período
                    weighted_days_sum += inv_days * daily_demand
                    total_daily_demand += daily_demand
            avg_inventory_days = round(weighted_days_sum / total_daily_demand, 1) if total_daily_demand > 0 else 0.0

            kpi_dict = {
                "total_trays": total_trays,
                "total_locations": total_trays,
                "skus_placed": len(placed_skus_in_storage),
                "avg_area_occupancy_pct": round(avg_occupancy, 2),
                "optimized": payload_data.optimize_trays,
                "total_wasted_vol": total_wasted_volume,
                "orders_satisfied": orders_satisfied,
                "orders_satisfied_pct": orders_satisfied_pct,
                "total_orders": total_orders,
                "avg_inventory_days": avg_inventory_days,
            }
            results_by_storage[st_key] = {"kpi": kpi_dict, "best_trays": locations_export, "locations": locations_export, "unassigned_skus": unassigned_skus, "unassigned_skus_details": unassigned_skus_details}
            print(f"   ✅ [Micro] {st_key}: {total_trays} bandejas, {len(placed_skus_in_storage)} SKUs colocados, {len(unassigned_skus)} rebotados")

        params_dict = {
            "cycle_days": payload_data.cycle_days,
            "n_vlms": payload_data.n_vlms,
            "n_trays_per_vlm": payload_data.n_trays_per_vlm,
            "include_zero_rot": payload_data.include_zero_rot,
            "optimize_trays": payload_data.optimize_trays,
            "opt_time_ms": payload_data.opt_time_ms,
            "weight_affinity": payload_data.weights.affinity,
            "weight_rotation": payload_data.weights.rotation,
            "weight_height": payload_data.weights.height,
            "storages": [s.model_dump() for s in payload_data.storages],
        }
        all_trays = [loc for r in results_by_storage.values() for loc in r.get("locations", r.get("best_trays", []))]
        total_trays_agg = sum(r["kpi"].get("total_trays", 0) for r in results_by_storage.values())
        avg_occ_list = [r["kpi"].get("avg_area_occupancy_pct", 0) for r in results_by_storage.values() if r["kpi"].get("total_trays", 0) > 0]
        total_wasted_agg = sum(r["kpi"].get("total_wasted_vol", 0) for r in results_by_storage.values())
        inv_days_list = [r["kpi"].get("avg_inventory_days", 0) for r in results_by_storage.values() if r["kpi"].get("total_trays", 0) > 0]

        # KPI global de pedidos: un pedido está satisfecho si TODOS sus SKUs están
        # colocados en ALGÚN tipo de almacenamiento (cross-storage)
        all_placed_skus = set()
        for r in results_by_storage.values():
            locs = r.get("locations", r.get("best_trays", []))
            for loc in locs:
                for item in (loc.get("items", []) if isinstance(loc, dict) else getattr(loc, "items", [])):
                    sid = item.get("sku", "") if isinstance(item, dict) else getattr(item, "sku_id", "")
                    all_placed_skus.add(str(sid).strip())
        global_orders_satisfied = 0
        total_orders_global = len(orders)
        for order in orders:
            order_sku_set = {str(s).strip() for s in order.sku_ids}
            if order_sku_set and order_sku_set.issubset(all_placed_skus):
                global_orders_satisfied += 1
        global_orders_satisfied_pct = round(global_orders_satisfied / total_orders_global * 100, 2) if total_orders_global > 0 else 0.0

        agg_kpi = {
            "total_trays": total_trays_agg,
            "avg_area_occupancy_pct": sum(avg_occ_list) / len(avg_occ_list) if avg_occ_list else 0,
            "optimized": payload_data.optimize_trays,
            "total_wasted_vol": round(total_wasted_agg, 4),
            "orders_satisfied": global_orders_satisfied,
            "orders_satisfied_pct": global_orders_satisfied_pct,
            "total_orders": total_orders_global,
            "avg_inventory_days": round(sum(inv_days_list) / len(inv_days_list), 1) if inv_days_list else 0,
        }
        # Guardar KPIs por storage en params para que el historial tenga detalle completo
        params_dict["kpis_by_storage"] = {st: r["kpi"] for st, r in results_by_storage.items()}
        exec_id = save_micro_execution(db, CURRENT_USER_ID, params_dict, agg_kpi, all_trays)

        response_data = {"status": "success", "results_by_storage": results_by_storage}
        print(f"📤 [RESPONSE MICRO]: {json.dumps(response_data, default=str)}")
        return response_data

    except Exception as e:
        logger.error(f"Error en micro: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if path_file.exists(): path_file.unlink()