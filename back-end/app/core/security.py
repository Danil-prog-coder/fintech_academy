import asyncio
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet

from app.core.config import get_settings

_hasher = PasswordHasher()
ALGORITHM = "HS256"


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password: str, password_hash: str) -> bool:
    def _check() -> bool:
        try:
            return _hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False

    return await asyncio.to_thread(_check)


def create_jwt(user_id: int, kind: str) -> str:
    s = get_settings()
    ttl = (
        timedelta(minutes=s.access_token_ttl_min)
        if kind == "access"
        else timedelta(days=s.refresh_token_ttl_days)
    )
    payload = {"sub": str(user_id), "type": kind, "exp": datetime.now(UTC) + ttl}
    return jwt.encode(payload, s.secret_key, algorithm=ALGORITHM)


def decode_jwt(token: str, kind: str) -> int | None:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if data.get("type") != kind:
        return None
    try:
        return int(data["sub"])
    except (KeyError, ValueError):
        return None


def new_api_token() -> tuple[str, str]:
    """Возвращает (токен для пользователя, хэш для БД)."""
    raw = "rsh_" + secrets.token_urlsafe(32)
    return raw, hash_api_token(raw)


def hash_api_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def encrypt_secret(value: str) -> str:
    return Fernet(get_settings().encryption_key.encode()).encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return Fernet(get_settings().encryption_key.encode()).decrypt(value.encode()).decode()
