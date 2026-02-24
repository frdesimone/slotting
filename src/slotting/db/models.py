import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from .database import Base

class Execution(Base):
    __tablename__ = "executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow)
    job_type = Column(String, nullable=False) # 'OUTLIERS', 'MACRO', 'MICRO'
    parameters = Column(JSONB, nullable=True)
    status = Column(String, default="SUCCESS")

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