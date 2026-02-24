from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from .database import Base

# 1. NUEVA TABLA DE USUARIOS (Preparada para Clerk)
class User(Base):
    __tablename__ = "users"

    # El ID será un String porque Clerk usa IDs como "user_2AbCdE..."
    id = Column(String, primary_key=True, index=True) 
    email = Column(String, nullable=True) # Opcional, Clerk ya lo guarda, pero sirve de backup
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relación
    executions = relationship("Execution", back_populates="owner")


# 2. MODIFICACIÓN A TU TABLA DE EJECUCIONES
class Execution(Base):
    __tablename__ = "executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # NUEVO: Llave foránea que apunta al usuario
    user_id = Column(String, ForeignKey("users.id"), index=True, nullable=False) 
    
    created_at = Column(DateTime, default=datetime.utcnow)
    job_type = Column(String, nullable=False)
    parameters = Column(JSONB, nullable=True)
    status = Column(String, default="SUCCESS")

    # Relaciones
    owner = relationship("User", back_populates="executions")
    macro_result = relationship("MacroResult", back_populates="execution", uselist=False)
    micro_result = relationship("MicroResult", back_populates="execution", uselist=False)

class MacroResult(Base):
    __tablename__ = "macro_results"

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id"))
    total_skus = Column(Integer)
    vlm_skus_count = Column(Integer)
    rack_skus_count = Column(Integer)
    vlm_fill_percentage = Column(Float)
    skus_details = Column(JSONB) # Lista de diccionarios

    execution = relationship("Execution", back_populates="macro_result")

class MicroResult(Base):
    __tablename__ = "micro_results"

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id"))
    total_trays = Column(Integer)
    avg_area_occupancy_pct = Column(Float)
    optimized = Column(Boolean)
    trays_export = Column(JSONB)

    execution = relationship("Execution", back_populates="micro_result")