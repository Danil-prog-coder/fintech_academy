"""FastAPI dependencies: the core, DB sessions, integration auth, panel sessions."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import Core
from ..db import sessionmaker
from ..errors import ApiError, forbidden, unauthorized
from ..models import Integration, Role
from ..services import accounts, integrations
from ..services.accounts import SESSION_COOKIE, PanelUser


def get_core(request: Request) -> Core:
    return request.app.state.core


async def get_db() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        yield session


async def integration(x_api_key: str | None = Header(default=None), core: Core = Depends(get_core),
                      db: AsyncSession = Depends(get_db)) -> Integration:
    integ = await integrations.authenticate(db, x_api_key)
    if not await core.limiter.hit(f"api:{integ.id}", core.settings.api_rate_per_minute, 60):
        raise ApiError(429, "rate_limited", "Слишком много запросов, повторите позже", retryable=True,
                       headers={"Retry-After": "60"})
    return integ


def client_ip(request: Request) -> str:
    # behind the site's nginx the real address is in X-Forwarded-For (first hop); fine for rate limiting only
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


async def panel_user(request: Request, db: AsyncSession = Depends(get_db)) -> PanelUser:
    """Cookie session. State-changing requests must carry `X-Requested-With: panel`: a cross-site form cannot set
    custom headers, and a cross-site fetch with it needs a CORS preflight we never allow — CSRF is closed."""
    user = await accounts.resolve(db, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise unauthorized("Сессия истекла, войдите снова")
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-requested-with") != "panel":
        raise forbidden("csrf", "Запрос без заголовка X-Requested-With: panel")
    return user


def require_roles(*roles: Role):
    async def dep(user: PanelUser = Depends(panel_user)) -> PanelUser:
        if user.role not in roles:
            raise forbidden("role_forbidden", "Этот раздел недоступен для вашей роли")
        return user

    return dep


managers = require_roles(Role.OWNER, Role.ADMIN)
support_staff = require_roles(Role.OWNER, Role.ADMIN, Role.SUPPORT)
owner_only = require_roles(Role.OWNER)
