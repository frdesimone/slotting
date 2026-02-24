import os
import shutil
import ipaddress
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

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
from slotting.algorithms.micro.optimization.optimizer import optimize, LocalSearchConfig

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


@app.post("/api/v1/outliers")
async def detectar_outliers_endpoint(
    pedidos_file: UploadFile = File(...),
    maestro_file: UploadFile = File(...),
    cycle_days: float = Form(15.0),
    token: str = Depends(verificar_token)
):
    """Detecta y retorna anomalías en el dataset."""
    path_pedidos = guardar_temp(pedidos_file)
    path_maestro = guardar_temp(maestro_file)
    
    try:
        # Cargar datos (Sin excluir nada)
        skus_dict, orders, _ = load_slotting_inputs_with_stats(
            codes_csv_path=path_maestro,
            orders_csv_path=path_pedidos,
            cycle_days=cycle_days,
            include_zero_rot=True
        )
        skus_list = list(skus_dict.values()) if isinstance(skus_dict, dict) else skus_dict

        # Detectar Outliers
        report = detect_outliers(skus_list, orders)
        
        # Formatear respuesta JSON para Retool
        return {
            "status": "success",
            "heavy_skus": [{"id": s.sku_id, "weight": s.weight} for s in report.heavy_skus],
            "bulky_skus": [{"id": s.sku_id, "volume": s.volume} for s in report.bulky_skus],
            "massive_orders": [{"id": o.order_id, "lines": len(o.sku_ids)} for o in report.massive_orders],
            "ubiquitous_skus": [{"id": s_id, "count": count, "pct": pct} for s_id, count, pct in report.ubiquitous_skus]
        }
    except Exception as e:
        logger.error(f"Error en outliers: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if path_pedidos.exists(): path_pedidos.unlink()
        if path_maestro.exists(): path_maestro.unlink()


@app.post("/api/v1/macro")
async def ejecutar_macro(
    pedidos_file: UploadFile = File(...),
    maestro_file: UploadFile = File(...),
    cycle_days: float = Form(15.0),
    vlm_volume: float = Form(60.0),
    vlm_occupancy: float = Form(0.85),
    token: str = Depends(verificar_token)
):
    """Ejecuta el Macro Slotting (Asignación a VLM)."""
    path_pedidos = guardar_temp(pedidos_file)
    path_maestro = guardar_temp(maestro_file)
    
    try:
        # 1. Cargar Datos
        skus_dict, orders, stats = load_slotting_inputs_with_stats(
            codes_csv_path=path_maestro,
            orders_csv_path=path_pedidos,
            cycle_days=cycle_days,
            include_zero_rot=True 
        )
        skus_list = list(skus_dict.values()) if isinstance(skus_dict, dict) else skus_dict

        # 2. Ejecutar Macro
        config = MacroSlottingConfig(
            vlm_total_usable_volume=vlm_volume,
            vlm_occupancy_target=vlm_occupancy
        )
        results = run_macro_slotting(skus_list, config)

        # 3. Preparar JSON de Respuesta
        vlm_results = [r for r in results if r.storage_type == "VLM"]
        rack_results = [r for r in results if r.storage_type == "RACK"]
        
        vlm_assigned_volume = sum(getattr(r, 'cycle_volume', 0) for r in vlm_results)
        target_vol = vlm_volume * vlm_occupancy
        fill_pct = (vlm_assigned_volume / target_vol) * 100 if target_vol > 0 else 0

        # Para alimentar la tabla del frontend
        vlm_skus_details = [{
            "sku_id": r.sku_id,
            "vol_cycle": getattr(r, 'cycle_volume', 0.0),
            "abc_class": getattr(r, 'abc_class', 'N/A')
        } for r in vlm_results]

        return {
            "status": "success",
            "kpi": {
                "total_skus": len(results),
                "vlm_skus_count": len(vlm_results),
                "rack_skus_count": len(rack_results),
                "vlm_volume_used": round(vlm_assigned_volume, 2),
                "vlm_volume_target": round(target_vol, 2),
                "vlm_fill_percentage": round(fill_pct, 1)
            },
            "vlm_skus": vlm_skus_details
        }
    except Exception as e:
        logger.error(f"Error en macro: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if path_pedidos.exists(): path_pedidos.unlink()
        if path_maestro.exists(): path_maestro.unlink()


@app.post("/api/v1/micro")
async def ejecutar_micro(
    pedidos_file: UploadFile = File(...),
    maestro_file: UploadFile = File(...), # Se espera que sea el filtrado del Macro
    cycle_days: float = Form(15.0),
    n_vlms: int = Form(10),
    n_trays_per_vlm: int = Form(100),
    include_zero_rot: bool = Form(False),
    optimize_trays: bool = Form(False),
    opt_time_ms: int = Form(10000),
    token: str = Depends(verificar_token)
):
    """Ejecuta el Micro Slotting (Armado de Bandejas), opcionalmente optimizado."""
    path_pedidos = guardar_temp(pedidos_file)
    path_maestro = guardar_temp(maestro_file)
    
    try:
        # 1. Cargar Datos
        skus_dict, orders, stats = load_slotting_inputs_with_stats(
            codes_csv_path=path_maestro,
            orders_csv_path=path_pedidos,
            cycle_days=cycle_days,
            include_zero_rot=include_zero_rot
        )
        skus_list = list(skus_dict.values()) if isinstance(skus_dict, dict) else skus_dict

        # 2. Configurar Micro
        config = MicroSlottingConfig(n_vlms=n_vlms, n_trays_per_vlm=n_trays_per_vlm, max_trays=n_vlms*n_trays_per_vlm)
        
        # 3. Flujo Core
        affinity_graph = build_affinity_graph(orders=orders, top_k=config.graph_top_k_neighbors, aff_min=config.graph_aff_min, metric=config.affinity_metric)
        groups = build_groups(skus=skus_list, orders=orders, config=config)
        selected_groups = select_groups(groups=groups, skus=skus_list, selection_cost_mode=config.selection_cost_mode)
        
        # Generar Greedy
        tray_plans = build_tray_plans(selected_groups=selected_groups, skus=skus_list, affinity_graph=affinity_graph, config=config)
        final_trays = [tray for plan in tray_plans for tray in plan.trays]

        # 4. Optimización (Si se pide)
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

        # 5. Preparar JSON de Respuesta
        if not final_trays:
            return {"status": "success", "kpi": {}, "trays": []}

        # Helpers para % de ocupación seguro
        def get_occ(t):
            return t.occupancy_percent if hasattr(t, 'occupancy_percent') else (getattr(t, 'area_used', 0)/getattr(t, 'max_area', 1))*100

        total_trays = len(final_trays)
        avg_occupancy = sum(get_occ(t) for t in final_trays) / total_trays if total_trays else 0

        # Formatear el top de bandejas para mostrar en UI
        trays_export = []
        for t in sorted(final_trays, key=lambda x: get_occ(x), reverse=True)[:50]: # Retornamos top 50 para no reventar el frontend
            trays_export.append({
                "tray_id": getattr(t, 'tray_id', 'N/A'),
                "occupancy_pct": round(get_occ(t), 2),
                "item_count": len(t.items),
                "items": [{"sku": i.sku_id, "vol": getattr(i, 'total_volume', 0)} for i in t.items[:5]] # Top 5 items de la bandeja
            })

        return {
            "status": "success",
            "kpi": {
                "total_trays": total_trays,
                "skus_placed": len(skus_list),
                "avg_area_occupancy_pct": round(avg_occupancy, 2),
                "optimized": optimize_trays
            },
            "best_trays": trays_export
        }

    except Exception as e:
        logger.error(f"Error en micro: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if path_pedidos.exists(): path_pedidos.unlink()
        if path_maestro.exists(): path_maestro.unlink()