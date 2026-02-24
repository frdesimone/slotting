import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# DO inyecta esto: postgresql://usuario:pass@host:puerto/db
# SQLAlchemy a veces requiere que empiece con postgresql:// en vez de postgres://
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/slotting_local")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Dependencia para FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()