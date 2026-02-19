import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from .config import get_settings
from .logging_config import configure_logging

logger = logging.getLogger("slotting")

# 1. Inicializar la app de FastAPI
app = FastAPI(title="Slotting API", description="API para el algoritmo de macro y micro slotting")

# 2. Configurar las IPs permitidas (AQUÍ PONES LAS IPS DESDE DONDE VAS A LLAMAR A LA API)
ALLOWED_IPS = {"127.0.0.1", "192.168.1.100"}  # Reemplaza con tus IPs reales

# 3. Middleware para restringir accesos
@app.middleware("http")
async def restrict_ips(request: Request, call_next):
    # En DigitalOcean App Platform, la IP del cliente viene en este header
    forwarded_for = request.headers.get("X-Forwarded-For")
    
    if forwarded_for:
        # Tomamos la primera IP en caso de que haya varios proxies
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        # Fallback para entorno local
        client_ip = request.client.host

    if client_ip not in ALLOWED_IPS:
        logger.warning(f"Acceso denegado a la IP: {client_ip}")
        return JSONResponse(status_code=403, content={"detail": "Access denied. IP not authorized."})
    
    response = await call_next(request)
    return response

# 4. Evento de inicio (reemplaza tu función main() anterior)
@app.on_event("startup")
def startup_event():
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Arrancando API de slotting (env=%s)", settings.env)

# 5. Endpoint de prueba / Healthcheck
@app.get("/")
def read_root():
    return {"status": "ok", "message": "API de Slotting funcionando y protegida."}

# (Opcional) Si quieres correrlo localmente ejecutando `python -m slotting.main`
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("slotting.main:app", host="0.0.0.0", port=8080, reload=True)