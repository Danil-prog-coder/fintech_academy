"""Shared runtime objects of the process (settings, crypto, limiter, RAG client, Jira factory)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from ..services.rag import RagClient
from .config import Settings
from .ratelimit import RateLimiter
from .security import SecretBox


@dataclass
class Core:
    settings: Settings
    box: SecretBox
    limiter: RateLimiter
    rag: RagClient
    # Outgoing HTTP (webhooks, Jira) goes through one client; tests swap the transport
    http: httpx.AsyncClient
    jira_factory: Callable | None = None
    extra: dict = field(default_factory=dict)

    async def close(self) -> None:
        await self.rag.close()
        await self.http.aclose()
        await self.limiter.close()


def build_core(settings: Settings, rag_transport: httpx.AsyncBaseTransport | None = None,
               http_transport: httpx.AsyncBaseTransport | None = None) -> Core:
    return Core(
        settings=settings,
        box=SecretBox(settings.secret_key),
        limiter=RateLimiter(settings.redis_url),
        rag=RagClient(settings.rag_url, settings.rag_api_token, settings.rag_timeout_s, transport=rag_transport),
        http=httpx.AsyncClient(transport=http_transport, timeout=httpx.Timeout(settings.webhook_timeout_s, connect=5.0),
                               follow_redirects=False),
    )
