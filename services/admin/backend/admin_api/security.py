"""Secrets: integration keys, project codes, panel passwords, sessions, encryption at rest, webhook signatures.

* Integration keys and session / setup tokens are high-entropy random strings: SHA-256 is enough to store them
  (no brute force on 256 bits), lookups are by hash.
* Project codes `<public_id>-<secret>` and panel passwords are verified with argon2id in a worker thread.
* Values that must be shown again (project code to the owner) or used (Jira token, webhook secret) are encrypted
  with Fernet; the key is derived from SECRET_KEY, so a database dump alone reveals nothing.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

_hasher = PasswordHasher()
# Unknown login / project: verify against this hash so the response time does not reveal what exists
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

PUBLIC_ID_RE = re.compile(r"^[0-9a-f]{8}$")
CODE_RE = re.compile(r"^[0-9a-f]{8}-[A-Za-z0-9_-]{24}$")


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_integration_key(slug: str) -> str:
    return f"ik_{slug}_{secrets.token_urlsafe(32)}"


def new_public_id() -> str:
    return secrets.token_hex(4)


def new_project_code(public_id: str) -> str:
    return f"{public_id}-{secrets.token_urlsafe(18)}"


def code_public_id(code: str) -> str | None:
    code = (code or "").strip()
    return code.split("-", 1)[0] if CODE_RE.match(code) else None


async def hash_secret(value: str) -> str:
    return await asyncio.to_thread(_hasher.hash, value)


async def verify_secret(value_hash: str | None, value: str) -> bool:
    def _verify() -> bool:
        try:
            return _hasher.verify(value_hash or _DUMMY_HASH, value)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    ok = await asyncio.to_thread(_verify)
    return ok and value_hash is not None


class SecretBox:
    def __init__(self, secret_key: str) -> None:
        digest = hashlib.sha256(b"admin-api:secret-box:" + secret_key.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str | None) -> str | None:
        if not token:
            return None
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken:
            return None


def sign_webhook(secret: str, body: bytes, timestamp: int | None = None) -> str:
    """`t=<unix>,v1=<hex>`: HMAC-SHA256 over `<t>.<body>`; the receiver rejects stale timestamps (replay)."""
    t = int(timestamp if timestamp is not None else time.time())
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify_webhook(secret: str, body: bytes, header: str, tolerance_s: int = 300, now: float | None = None) -> bool:
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs((now or time.time()) - t) > tolerance_s:
        return False
    expected = sign_webhook(secret, body, t).split("v1=", 1)[1]
    return hmac.compare_digest(expected, parts.get("v1", ""))


LOGIN_RE = re.compile(r"^[a-z0-9._@-]{3,64}$")
PASSWORD_MIN, PASSWORD_MAX = 10, 128


def normalize_login(login: str) -> str:
    return (login or "").strip().lower()
