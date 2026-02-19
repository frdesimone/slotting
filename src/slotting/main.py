import os
import shutil
import ipaddress
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .config import get_settings
from .logging_config import configure_logging
# IMPORTANTE: Aquí importarás tus funciones reales de slotting cuando las conectemos
# from .algorithms.common.prep.orders import load_orders_from_pedidos
# from .algorithms.macro... import ejecutar_macro_slotting
# from .algorithms.micro... import ejecutar_micro_slotting

logger = logging.getLogger("slotting")

# ==========================================
# 1. CONFIGURACIÓN DE APP Y SEGURIDAD
# ==========================================
app = FastAPI(title="Slotting API", description="API para algoritmos de Macro y Micro Slotting")

# Levantamos el token de las variables de entorno (con un fallback para desarrollo local)
API_TOKEN = os.environ.get("API_TOKEN", "token_desarrollo_local_123")
security = HTTPBearer()

def verificar_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Valida que el Bearer Token recibido coincida con la variable de entorno."""
    if credentials.credentials != API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


# ==========================================
# 2. FIREWALL POR CÓDIGO (RESTRICCIÓN DE IPs)
# ==========================================
ALLOWED_CIDRS = [
    ipaddress.ip_network("35.90.103.132/30"),  # Retool
    ipaddress.ip_network("44.208.168.68/30"),  # Retool
    ipaddress.ip_network("127.0.0.0/8")        # Localhost (para pruebas)
]

@app.middleware("http")
async def restrict_ips(request: Request, call_next):
    forwarded_for = request.headers.get("X-Forwarded-For")
    
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host

    try:
        ip_obj = ipaddress.ip_address(client_ip)
        is_allowed = any(ip_obj in network for network in ALLOWED_CIDRS)
        
        if not is_allowed:
            logger.warning(f"Acceso denegado a la IP: {client_ip}")
            return JSONResponse(
                status_code=403, 
                content={"detail": f"Access denied. IP {client_ip} not authorized."}
            )
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid IP format."})
    
    return await call_next(request)


# ==========================================
# 3. UTILIDADES
# ==========================================
def guardar_temp(upload_file: UploadFile) -> Path:
    """Guarda un UploadFile en el disco efímero de App Platform y retorna su Path."""
    temp_path = Path(f"/tmp/{upload_file.filename}")
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return temp_path


# ==========================================
# 4. ENDPOINTS
# ==========================================

@app.get("/")
def read_root():
    return {"status": "ok", "message": "API de Slotting operativa."}

@app.post("/api/v1/outliers")
async def detectar_outliers(
    pedidos_file: UploadFile = File(...),
    token: str = Depends(verificar_token)
):
    if not pedidos_file.filename.endswith(('.csv', '.xlsx')):
        raise HTTPException(status_code=400, detail="El archivo debe ser CSV o Excel")

    temp_path = guardar_temp(pedidos_file)
    try:
        # Aquí llamas a tu función:
        # orders, rot, units, stats = load_orders_from_pedidos(path=temp_path)
        
        return {
            "endpoint": "outliers",
            "mensaje": f"Archivo {pedidos_file.filename} analizado",
            "resultados": "Lógica de outliers pendiente de conectar..."
        }
    finally:
        if temp_path.exists(): temp_path.unlink()


@app.post("/api/v1/macro")
async def ejecutar_macro(
    pedidos_file: UploadFile = File(...),
    maestro_file: UploadFile = File(...), # Suponiendo que macro necesita el catálogo
    token: str = Depends(verificar_token)
):
    path_pedidos = guardar_temp(pedidos_file)
    path_maestro = guardar_temp(maestro_file)
    
    try:
        # Aquí irá la lógica del Paso 1 al Paso 4 de tu doc de Macro-slotting
        return {
            "endpoint": "macro-slotting",
            "mensaje": "Archivos recibidos correctamente",
            "archivos_procesados": [pedidos_file.filename, maestro_file.filename]
        }
    finally:
        if path_pedidos.exists(): path_pedidos.unlink()
        if path_maestro.exists(): path_maestro.unlink()


@app.post("/api/v1/micro")
async def ejecutar_micro(
    pedidos_file: UploadFile = File(...),
    maestro_file: UploadFile = File(...),
    token: str = Depends(verificar_token)
):
    path_pedidos = guardar_temp(pedidos_file)
    path_maestro = guardar_temp(maestro_file)
    
    try:
        # Aquí irá la lógica de grupos, subgrupos y asignación a bandejas
        return {
            "endpoint": "micro-slotting",
            "mensaje": "Archivos recibidos correctamente",
            "archivos_procesados": [pedidos_file.filename, maestro_file.filename]
        }
    finally:
        if path_pedidos.exists(): path_pedidos.unlink()
        if path_maestro.exists(): path_maestro.unlink()