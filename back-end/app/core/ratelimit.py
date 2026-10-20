"""Ограничение частоты запросов: скользящее окно в памяти процесса.

При нескольких процессах API лимит считается отдельно в каждом; для MVP этого достаточно,
а на проде лимит можно дополнительно задать на уровне nginx.
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Depends, Request

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import User

_hits: dict[str, deque[float]] = defaultdict(deque)


def reset() -> None:
    _hits.clear()


def _check(key: str, limit: int, window_sec: int) -> None:
    now = time.monotonic()
    hits = _hits[key]
    while hits and now - hits[0] >= window_sec:
        hits.popleft()
    if len(hits) >= limit:
        raise AppError(
            "rate_limited", "Слишком много запросов. Попробуйте чуть позже.", 429, retryable=True
        )
    hits.append(now)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def per_ip(name: str, limit: int, window_sec: int = 60) -> Callable:
    """Зависимость: не больше `limit` запросов за окно с одного IP."""

    async def dependency(request: Request) -> None:
        if get_settings().rate_limit_enabled:
            _check(f"{name}:ip:{client_ip(request)}", limit, window_sec)

    return Depends(dependency)


def per_user(name: str, limit: int, window_sec: int = 60) -> Callable:
    """Зависимость: не больше `limit` запросов за окно от одного пользователя."""

    async def dependency(user: User = Depends(current_user)) -> None:
        if get_settings().rate_limit_enabled:
            _check(f"{name}:user:{user.id}", limit, window_sec)

    return Depends(dependency)
