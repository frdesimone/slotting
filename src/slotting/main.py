import os
import shutil
import ipaddress
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
import json

from sqlalchemy.orm import Session

from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Request, Form
from fastapi.responses import JSONResponse
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
    col_pedido_cant: str = Form("Cantidad unidades"),
    
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
        skus_dict, orders, _ = load_slotting_inputs_with_stats(
            file_path=path_file, # <-- CAMBIO CLAVE
            cycle_days=cycle_days,
            include_zero_rot=True,
            mapping=mapping_config
        )
        skus_list = list(skus_dict.values()) if isinstance(skus_dict, dict) else skus_dict

        rules_list = []
        try:
            if outliers_config and outliers_config.strip():
                parsed = json.loads(outliers_config)
                rules_list = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            logger.warning(f"outliers_config inválido, usando defaults: {outliers_config}")

        report = detect_outliers(skus_list, orders, rules=rules_list)
        sku_by_id = {s.sku_id: s for s in skus_list}

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
        response_data = {"status": "success", "categories": categories}
        
        # Imprimir en los logs
        print(f"📤 [RESPONSE OUTLIERS]: {json.dumps(response_data, default=str)}")
        
        return response_data
    
    except Exception as e:
        logger.error(f"Error en outliers: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if path_file.exists(): path_file.unlink() # Borramos el temporal

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
    col_pedido_cant: str = Form("Cantidad unidades"),
    
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

        config = MacroSlottingConfig(storage_types=st_list, abc_thresholds=(0.80, 0.95))
        results = run_macro_slotting(skus_list, config)

        sku_by_id = {s.sku_id: s for s in skus_list}

        # --- ARMADO DINÁMICO DE KPIS ---
        kpi_dict = {
            "total_skus": len(results),
            "allocations": {}
        }

        vlm_skus_details = []
        for st in st_list:
            st_name = st["name"]
            st_results = [r for r in results if r.storage_type == st_name]
            st_vol_used = sum(getattr(r, 'cycle_volume', 0) for r in st_results)
            st_target = float(st.get("capacity", 0)) * float(st.get("occupancy", 1))
            fill_pct = (st_vol_used / st_target) * 100 if st_target > 0 else 0
            
            kpi_dict["allocations"][st_name] = {
                "skus_count": len(st_results),
                "volume_used": round(st_vol_used, 2),
                "volume_target": round(st_target, 2),
                "fill_percentage": round(fill_pct, 1)
            }
            
            vlm_skus_details.extend([{
                "sku_id": r.sku_id, "storage_type": r.storage_type,
                "vol_cycle": getattr(r, 'cycle_volume', 0.0), "abc_class": getattr(r, 'abc_class', 'N/A'),
                "description": getattr(r, 'description', '') or '',
                "boxes_per_m3": getattr(r, 'boxes_per_m3', 0.0) or 0.0,
                "category": getattr(r, 'category', '') or '',
                "weight": getattr(sku_by_id.get(r.sku_id), 'weight', None) or 0.0,
            } for r in st_results])

        unassigned = [r for r in results if r.storage_type == "UNASSIGNED"]
        kpi_dict["unassigned_count"] = len(unassigned)
        vlm_skus_details.extend([{
            "sku_id": r.sku_id, "storage_type": r.storage_type,
            "vol_cycle": getattr(r, 'cycle_volume', 0.0), "abc_class": getattr(r, 'abc_class', 'N/A'),
            "description": getattr(r, 'description', '') or '',
            "boxes_per_m3": getattr(r, 'boxes_per_m3', 0.0) or 0.0,
            "category": getattr(r, 'category', '') or '',
            "weight": getattr(sku_by_id.get(r.sku_id), 'weight', None) or 0.0,
        } for r in unassigned])

        params_dict = {"storage_types": st_list}
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
    file: UploadFile = File(...), # <-- 1. UN SOLO ARCHIVO
    cycle_days: float = Form(15.0),
    vlm_skus_ids: str = Form("[]"),
    n_vlms: int = Form(10),
    n_trays_per_vlm: int = Form(100),
    include_zero_rot: bool = Form(False),
    optimize_trays: bool = Form(False),
    opt_time_ms: int = Form(10000),
    
    # --- 2. MAPEO DINÁMICO ---
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
    col_pedido_cant: str = Form("Cantidad unidades"),
    # -------------------------
    
    token: str = Depends(verificar_token),
    db: Session = Depends(get_db)
):
    """Ejecuta el Micro Slotting (Armado de Bandejas), opcionalmente optimizado."""
    path_file = guardar_temp(file)
    CURRENT_USER_ID = "frontend_user_mock_123"
    
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

        # 1. Parseamos el JSON y forzamos a que todo sea texto sin espacios
        raw_vlm_ids = json.loads(vlm_skus_ids)
        allowed_vlm_skus = set(str(sku_id).strip() for sku_id in raw_vlm_ids)
        
        print(f"🚀 [Micro] Recibidos {len(allowed_vlm_skus)} SKUs para procesar.")

        # ... (la llamada a load_slotting_inputs_with_stats queda igual) ...
        skus_list, orders, stats = load_slotting_inputs_with_stats(
            file_path=path_file,
            cycle_days=cycle_days,
            period_days=180.0,
            include_zero_rot=include_zero_rot,
            mapping=mapping_config,
            excluded_skus=None
        )

        # 2. Forzamos el ID del objeto también a texto para comparar "peras con peras"
        if allowed_vlm_skus:
            skus_list = [s for s in skus_list if str(s.sku_id).strip() in allowed_vlm_skus]
            print(f"✅ [Micro] Lista filtrada a {len(skus_list)} SKUs.")

            orders = _filter_orders_by_skus(orders, skus_list, stats)
            print(f"✅ [Micro] Órdenes sincronizadas con los SKUs válidos.")

        if not skus_list:
            raise ValueError("No hay SKUs válidos para procesar en Micro después del filtro.")

        config = MicroSlottingConfig(
            cycle_days=cycle_days,
            max_trays=9999  # Un número altísimo para evitar el ValueError
        )
        
        affinity_graph = build_affinity_graph(orders=orders, top_k=config.graph_top_k_neighbors, aff_min=config.graph_aff_min, metric=config.affinity_metric)
        groups = build_groups(skus=skus_list, orders=orders, config=config)
        selected_groups = select_groups(groups=groups, skus=skus_list, selection_cost_mode=config.selection_cost_mode)
        
        tray_plans = build_tray_plans(selected_groups=selected_groups, skus=skus_list, affinity_graph=affinity_graph, config=config)
        final_trays = [tray for plan in tray_plans for tray in plan.trays]

        if optimize_trays and final_trays:
            sku_by_id = {sku.sku_id: sku for sku in skus_list}
            subgroup_lookup = {sg.subgroup_id: sg for plan in tray_plans for sg in plan.subgroups}
            
            hybrid = build_hybrid_kpi_state(
                subgroups=list(subgroup_lookup.values()),
                trays=final_trays,
                sku_by_id=sku_by_id,
                affinity_graph=affinity_graph,
                config=config,
            )
            
            opt_config = LocalSearchConfig(time_budget_ms=opt_time_ms, allow_annealing=True)
            optimize(hybrid, opt_config)
            final_trays = hybrid.all_trays()

        if not final_trays:
            return {"status": "success", "kpi": {}, "trays": []}

        def get_occ(t):
            return t.occupancy_percent if hasattr(t, 'occupancy_percent') else (getattr(t, 'area_used', 0)/getattr(t, 'max_area', 1))*100

        total_trays = len(final_trays)
        avg_occupancy = sum(get_occ(t) for t in final_trays) / total_trays if total_trays else 0

        trays_export = []
        for t in sorted(final_trays, key=lambda x: get_occ(x), reverse=True): # Sin [:50]
            trays_export.append({
                "tray_id": getattr(t, 'tray_id', 'N/A'),
                "occupancy_pct": round(get_occ(t), 2),
                "item_count": len(t.items),
                # Mandamos TODOS los items de la bandeja
                "items": [{"sku": i.sku_id, "vol": getattr(i, 'total_volume', 0)} for i in t.items] 
            })

        kpi_dict = {
            "total_trays": total_trays,
            "skus_placed": len(skus_list),
            "avg_area_occupancy_pct": round(avg_occupancy, 2),
            "optimized": optimize_trays
        }

        params_dict = {
            "cycle_days": cycle_days,
            "n_vlms": n_vlms,
            "n_trays_per_vlm": n_trays_per_vlm,
            "include_zero_rot": include_zero_rot,
            "optimize_trays": optimize_trays,
            "opt_time_ms": opt_time_ms
        }

        exec_id = save_micro_execution(db, CURRENT_USER_ID, params_dict, kpi_dict, trays_export)
        print(f"Ejecución Micro guardada exitosamente en DB con ID: {exec_id}")

        response_data = {
            "status": "success",
            "execution_id": str(exec_id), 
            "kpi": kpi_dict,
            "best_trays": trays_export
        }
        
        print(f"📤 [RESPONSE MICRO]: {json.dumps(response_data, default=str)}")
        
        return response_data

    except Exception as e:
        logger.error(f"Error en micro: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if path_file.exists(): path_file.unlink()