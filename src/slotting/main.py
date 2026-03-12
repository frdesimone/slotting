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
        total_lineas = int(order_stats.kept_rows) if order_stats else 0  # Renglones del pedido
        total_unidades = float(order_stats.total_units) if order_stats else 0.0  # Suma de cantidades (qty)
        total_kg = 0.0
        total_m3 = 0.0
        period_days = float(getattr(order_stats, "period_days", 180.0)) if order_stats else 180.0
        cycle_days = 30.0

        for o in orders:
            for sid in o.sku_ids:
                sku_obj = sku_by_id.get(sid)
                if sku_obj:
                    if getattr(sku_obj, "weight", None):
                        try:
                            total_kg += float(sku_obj.weight)
                        except (ValueError, TypeError):
                            pass
                    vol_unit = float(getattr(sku_obj, "volume", 0) or getattr(sku_obj, "vol_unit", 0) or 0)
                    units_per_day = float(getattr(sku_obj, "units_sold_total", 0) or 0) / period_days if period_days > 0 else 0.0
                    if vol_unit > 0:
                        if units_per_day > 0:
                            total_m3 += vol_unit * units_per_day * cycle_days
                        else:
                            total_m3 += vol_unit

        lineas_por_pedido = total_lineas / total_pedidos if total_pedidos > 0 else 0.0

        summary_stats = {
            "total_skus": total_skus,
            "total_pedidos": total_pedidos,
            "total_unidades": int(total_unidades) if total_unidades == int(total_unidades) else round(total_unidades, 2),
            "total_lineas": total_lineas,
            "lineas_por_pedido": round(lineas_por_pedido, 2),
            "total_kg": round(total_kg, 2),
            "total_m3": round(total_m3, 3),
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
        response_data = {
            "status": "success",
            "summary": summary_stats,
            "categories": categories,
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
            include_zero_rot=True,
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
                group_min_delta=-5.0,
                subgroup_min_delta=-5.0,
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
                        ct_max_a = getattr(ct, "max_area", float("inf")) or float("inf")

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
                        t.area_used, t.weight_used = calc_tray_metrics(t_items, storage_cfg, sku_by_id)
                        compacted_trays.append(t)
                final_trays = compacted_trays

            # --- CORTE FINAL POR CAPACIDAD FÍSICA REAL ---
            qty_limit = int(getattr(storage_cfg, "qty", None) or getattr(storage_cfg, "max_trays", 999999) or 999999)
            if len(final_trays) > qty_limit:
                print(f"⚠️ Recortando de {len(final_trays)} a {qty_limit} bandejas/ubicaciones en {st_key}")
                final_trays = final_trays[:qty_limit]

            if not final_trays:
                results_by_storage[st_key] = {"kpi": {"total_trays": 0, "total_locations": 0, "skus_placed": len(skus_for_storage), "avg_area_occupancy_pct": 0, "optimized": payload_data.optimize_trays}, "best_trays": [], "locations": []}
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

            locations_export = []
            for t in sorted(final_trays, key=lambda x: get_occ(x), reverse=True):
                raw_tray_id = getattr(t, "tray_id", "N/A")
                clean_tray_id = str(raw_tray_id).replace("unassigned-unassigned-", f"{st_key}-1-")
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
                tray_wasted_vol = 0.0
                for i in final_items:
                    h = i.get("height", 0.0)
                    if h > 0 and tray_max_height > h:
                        base_area_m2 = i["vol"] / (h / 100.0)
                        wasted = base_area_m2 * ((tray_max_height - h) / 100.0)
                        tray_wasted_vol += wasted
                total_wasted_volume += tray_wasted_vol

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
                    })

                locations_export.append({
                    "location_id": clean_tray_id,
                    "occupancy_pct": round(get_occ(t), 2),
                    "max_height": tray_max_height,
                    "wasted_vol": tray_wasted_vol,
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

            kpi_dict = {
                "total_trays": total_trays,
                "total_locations": total_trays,
                "skus_placed": len(skus_for_storage),
                "avg_area_occupancy_pct": round(avg_occupancy, 2),
                "optimized": payload_data.optimize_trays,
                "total_wasted_vol": total_wasted_volume,
            }
            results_by_storage[st_key] = {"kpi": kpi_dict, "best_trays": locations_export, "locations": locations_export}
            print(f"   ✅ [Micro] {st_key}: {total_trays} bandejas, {len(skus_for_storage)} SKUs.")

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
        agg_kpi = {
            "total_trays": total_trays_agg,
            "avg_area_occupancy_pct": sum(avg_occ_list) / len(avg_occ_list) if avg_occ_list else 0,
            "optimized": payload_data.optimize_trays,
        }
        exec_id = save_micro_execution(db, CURRENT_USER_ID, params_dict, agg_kpi, all_trays)

        response_data = {"status": "success", "results_by_storage": results_by_storage}
        print(f"📤 [RESPONSE MICRO]: {json.dumps(response_data, default=str)}")
        return response_data

    except Exception as e:
        logger.error(f"Error en micro: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if path_file.exists(): path_file.unlink()