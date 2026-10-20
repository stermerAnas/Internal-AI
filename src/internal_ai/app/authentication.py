import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select

from internal_ai.app.config import Settings
from internal_ai.app.database import Users, get_db

bearer_scheme = HTTPBearer()
settings = Settings()
password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    hashed = password_hash.hash(password)
    return hashed


def verify_hashed_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_token(user_id: int) -> str:
    expiration = datetime.now(UTC) + timedelta(minutes=30)
    payload = {"sub": str(user_id), "exp": expiration}
    token = jwt.encode(payload=payload, key=settings.jwt_secret_key, algorithm="HS256")
    return token


def create_refresh_token() -> tuple[str, datetime]:
    refresh_token = secrets.token_urlsafe(32)
    refresh_expiration = datetime.now(UTC) + timedelta(days=7)
    return refresh_token, refresh_expiration


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_current_user(
    db=Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms="HS256")
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token,try refreshing the token via /auth/refresh",
        )
    try:
        user_id = int(payload.get("sub"))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="invalid token")
    stmt = select(Users).where(Users.id == user_id)
    user_exists = db.scalars(stmt).one_or_none()
    if user_exists is None:
        raise HTTPException(status_code=401, detail="This user doesn't exist")
    return user_exists
