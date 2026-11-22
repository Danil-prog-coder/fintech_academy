"""Fixed-window rate limiter: Redis when REDIS_URL is set (shared by all API processes), memory otherwise."""

from __future__ import annotations

import time
from collections import defaultdict

try:
    from redis import asyncio as aioredis
except ImportError:  # pragma: no cover
    aioredis = None


class RateLimiter:
    def __init__(self, redis_url: str = "") -> None:
        self._redis = aioredis.from_url(redis_url) if (redis_url and aioredis) else None
        self._mem: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    async def hit(self, key: str, limit: int, window_s: int) -> bool:
        """Count one hit; False — the limit for this window is exhausted."""
        if limit <= 0:
            return True
        bucket = int(time.time() // window_s)
        if self._redis is not None:
            try:
                k = f"rl:{key}:{bucket}"
                n = await self._redis.incr(k)
                if n == 1:
                    await self._redis.expire(k, window_s)
                return n <= limit
            except Exception:  # noqa: BLE001  (a Redis outage must not take the API down)
                pass
        count, b = self._mem[key]
        if b != bucket:
            count = 0
        count += 1
        self._mem[key] = (count, bucket)
        if len(self._mem) > 50_000:
            self._mem.clear()
        return count <= limit

    async def reset(self, key: str, window_s: int) -> None:
        bucket = int(time.time() // window_s)
        if self._redis is not None:
            try:
                await self._redis.delete(f"rl:{key}:{bucket}")
            except Exception:  # noqa: BLE001
                pass
        self._mem.pop(key, None)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
