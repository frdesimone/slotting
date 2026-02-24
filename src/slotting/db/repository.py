from sqlalchemy.orm import Session
from .models import Execution, MacroResult, MicroResult, User

# Función helper para el mock de usuarios (hasta que instales Clerk)
def get_or_create_user(db: Session, user_id: str, email: str = "mock@slotting.com"):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        user = User(id=user_id, email=email)
        db.add(user)
        db.commit()
    return user

def save_macro_execution(db: Session, user_id: str, params: dict, kpi: dict, skus_details: list):
    # Aseguramos que el usuario exista
    get_or_create_user(db, user_id)

    # 1. Crear la ejecución padre atada al user_id
    db_exec = Execution(user_id=user_id, job_type="MACRO", parameters=params)
    db.add(db_exec)
    db.flush() # Para obtener el ID generado sin commitear aún

    # 2. Crear los resultados atados al padre
    db_macro = MacroResult(
        execution_id=db_exec.id,
        total_skus=kpi.get("total_skus", 0),
        vlm_skus_count=kpi.get("vlm_skus_count", 0),
        rack_skus_count=kpi.get("rack_skus_count", 0),
        vlm_fill_percentage=kpi.get("vlm_fill_percentage", 0.0),
        skus_details=skus_details
    )
    db.add(db_macro)
    db.commit()
    db.refresh(db_exec)
    return db_exec.id

def save_micro_execution(db: Session, user_id: str, params: dict, kpi: dict, trays_export: list):
    # Aseguramos que el usuario exista
    get_or_create_user(db, user_id)

    db_exec = Execution(user_id=user_id, job_type="MICRO", parameters=params)
    db.add(db_exec)
    db.flush()

    db_micro = MicroResult(
        execution_id=db_exec.id,
        total_trays=kpi.get("total_trays", 0),
        avg_area_occupancy_pct=kpi.get("avg_area_occupancy_pct", 0.0),
        optimized=kpi.get("optimized", False),
        trays_export=trays_export
    )
    db.add(db_micro)
    db.commit()
    return db_exec.id

# --- LA CLAVE DEL MULTI-TENANT ---
def get_user_executions(db: Session, user_id: str):
    """Retorna TODAS las ejecuciones filtradas estrictamente por el usuario."""
    return db.query(Execution).filter(Execution.user_id == user_id).all()