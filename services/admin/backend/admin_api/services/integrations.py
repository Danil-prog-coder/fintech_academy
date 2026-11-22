"""Integrations: who may call the API. A key is shown once; the database keeps only its SHA-256."""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import Core
from ..db import utc_now
from ..errors import unauthorized
from ..models import Integration
from ..security import new_integration_key, new_token, sha256
from .events import check_webhook_url

log = logging.getLogger(__name__)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")


async def authenticate(session: AsyncSession, key: str | None) -> Integration:
    if not key:
        raise unauthorized("Нужен заголовок X-Api-Key")
    integ = await session.scalar(select(Integration).where(Integration.key_hash == sha256(key.strip())))
    if integ is None or integ.revoked_at is not None:
        raise unauthorized("Неизвестный или отозванный ключ интеграции")
    return integ


async def create(session: AsyncSession, slug: str, name: str, key: str | None = None) -> tuple[Integration, str]:
    if not SLUG_RE.match(slug):
        raise ValueError("slug: a-z, 0-9 and «-», 2–32 characters")
    key = key or new_integration_key(slug)
    if len(key) < 32:
        raise ValueError("integration key must be at least 32 characters")
    integ = Integration(slug=slug, name=name[:128], key_hash=sha256(key), key_prefix=key[:12])
    session.add(integ)
    await session.flush()
    return integ, key


async def rotate_key(session: AsyncSession, integ: Integration) -> str:
    key = new_integration_key(integ.slug)
    integ.key_hash, integ.key_prefix = sha256(key), key[:12]
    return key


async def bootstrap(session: AsyncSession, spec: str) -> None:
    """BOOTSTRAP_INTEGRATIONS="slug:Name:key;…" — idempotent: an existing slug gets the key from the spec."""
    for item in filter(None, (x.strip() for x in spec.split(";"))):
        try:
            slug, name, key = item.split(":", 2)
        except ValueError:
            log.error("BOOTSTRAP_INTEGRATIONS: bad item (expected slug:Name:key)")
            continue
        existing = await session.scalar(select(Integration).where(Integration.slug == slug))
        if existing is None:
            await create(session, slug, name, key)
            log.info("integration %s created from BOOTSTRAP_INTEGRATIONS", slug)
        elif existing.key_hash != sha256(key):
            existing.key_hash, existing.key_prefix, existing.revoked_at = sha256(key), key[:12], None
            log.info("integration %s: key updated from BOOTSTRAP_INTEGRATIONS", slug)
    await session.commit()


async def set_webhook(core: Core, session: AsyncSession, integ: Integration, url: str) -> str:
    """Set the URL and issue a new signing secret (shown once)."""
    integ.webhook_url = check_webhook_url(url, core.settings.webhook_allow_private)
    secret = "whsec_" + new_token(32)
    integ.webhook_secret_enc = core.box.encrypt(secret)
    await session.commit()
    return secret


async def clear_webhook(session: AsyncSession, integ: Integration) -> None:
    integ.webhook_url = integ.webhook_secret_enc = None
    await session.commit()


async def revoke(session: AsyncSession, integ: Integration) -> None:
    integ.revoked_at = utc_now()
    await session.commit()
