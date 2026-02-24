from sqlalchemy.orm import Session
from .models import Execution, MacroResult, MicroResult

def save_macro_execution(db: Session, params: dict, kpi: dict, skus_details: list):
    # 1. Crear la ejecución padre
    db_exec = Execution(job_type="MACRO", parameters=params)
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

def save_micro_execution(db: Session, params: dict, kpi: dict, trays_export: list):
    db_exec = Execution(job_type="MICRO", parameters=params)
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