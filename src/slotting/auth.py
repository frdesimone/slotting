"""Módulo de autenticación: hashing de passwords, JWT y dependencies de FastAPI."""
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .db.database import SessionLocal, get_db
from .db.models import User

# ==========================================
# Config
# ==========================================
JWT_SECRET = os.environ.get("JWT_SECRET", "dev_secret_change_me_in_prod_please")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "7"))

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "escala")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "slotting")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=True)


# ==========================================
# Password hashing
# ==========================================
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


# ==========================================
# JWT
# ==========================================
def create_access_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


# ==========================================
# Dependencies
# ==========================================
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario deshabilitado",
        )
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de administrador",
        )
    return user


# ==========================================
# Migración de esquema (ALTER TABLE aditivo)
# ==========================================
def run_user_schema_migration():
    """Agrega las columnas nuevas a users si no existen. Idempotente."""
    from sqlalchemy import text
    from .db.database import engine

    with engine.begin() as conn:
        statements = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR UNIQUE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS logo_data BYTEA",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS logo_mime VARCHAR",
            "CREATE INDEX IF NOT EXISTS ix_users_username ON users (username)",
        ]
        for stmt in statements:
            conn.execute(text(stmt))


# ==========================================
# Bootstrap: seed admin + migración de user mock → bremen
# ==========================================
def bootstrap_users():
    """Al levantar la app: garantiza admin y migra el mock histórico a 'bremen'."""
    run_user_schema_migration()

    db = SessionLocal()
    try:
        print(f"🔐 [auth] Bootstrap iniciado. ADMIN_USERNAME={ADMIN_USERNAME!r}")

        # 1. Seed del admin (idempotente + auto-reset de password)
        admin = db.query(User).filter(User.username == ADMIN_USERNAME).first()
        if not admin:
            admin = User(
                id=f"admin_{uuid.uuid4().hex[:12]}",
                username=ADMIN_USERNAME,
                email=f"{ADMIN_USERNAME}@slotting.local",
                password_hash=hash_password(ADMIN_PASSWORD),
                is_admin=True,
                is_active=True,
            )
            db.add(admin)
            print(f"🔐 [auth] Admin '{ADMIN_USERNAME}' CREADO.")
        else:
            # El admin ya existe — siempre re-asegurar password, flags y rol.
            # Esto permite resetear el password cambiando ADMIN_PASSWORD en el env y redeployando.
            admin.password_hash = hash_password(ADMIN_PASSWORD)
            admin.is_admin = True
            admin.is_active = True
            if not admin.email:
                admin.email = f"{ADMIN_USERNAME}@slotting.local"
            print(f"🔐 [auth] Admin '{ADMIN_USERNAME}' ACTUALIZADO (password resincronizado desde env).")

        # 2. Migrar el user mock legacy a 'bremen'
        MOCK_ID = "frontend_user_mock_123"
        bremen = db.query(User).filter(User.id == MOCK_ID).first()
        if bremen:
            if not bremen.username:
                bremen.username = "bremen"
            if not bremen.password_hash:
                # Password placeholder: el admin puede setearla después.
                # Dejo un hash inválido → el user no puede loguear hasta que se le setee una real.
                bremen.password_hash = hash_password(uuid.uuid4().hex)
            if bremen.email is None:
                bremen.email = "bremen@slotting.local"
            bremen.is_active = True
            bremen.is_admin = False
            print(f"🔐 [auth] User mock migrado a 'bremen' (id={MOCK_ID}).")
        else:
            # No hay ejecuciones previas del mock, pero creamos igual el user 'bremen'
            # por si tiene ejecuciones futuras asignadas manualmente.
            existing_bremen = db.query(User).filter(User.username == "bremen").first()
            if not existing_bremen:
                bremen = User(
                    id=MOCK_ID,
                    username="bremen",
                    email="bremen@slotting.local",
                    password_hash=hash_password(uuid.uuid4().hex),
                    is_admin=False,
                    is_active=True,
                )
                db.add(bremen)
                print("🔐 [auth] User 'bremen' creado.")

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"⚠️  [auth] Error en bootstrap_users: {e}")
        raise
    finally:
        db.close()
