"""Admin service: the platform core.

* `/v1/*` — open API for integrations (X-Api-Key);
* `/panel/api/*` — API of the site for owners, admins and support (cookie session);
* `/v1/public/rag/documents/*`, `/jira/webhook/*` — signed public entry points;
* background workers: webhook delivery, the Jira mirror, following indexing jobs.
The RAG service is reachable only from here.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from . import __version__, db, errors
from .api import panel, public, v1
from .config import Settings, get_settings
from .core import Core, build_core
from .rag_client import RagError, RagUnavailable
from .services import docs, escalations, events, integrations

log = logging.getLogger("admin_api")


async def _worker(core: Core, name: str, fn, interval: float) -> None:
    while True:
        try:
            async with db.sessionmaker()() as session:
                await fn(core, session)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  (a worker never dies; the next pass retries)
            log.exception("worker %s failed", name)
        await asyncio.sleep(interval)


def create_app(settings: Settings | None = None, core: Core | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if db._engine is None:
            db.init_engine(settings.database_url)
        app.state.core = core or build_core(settings)
        if settings.bootstrap_integrations:
            async with db.sessionmaker()() as session:
                await integrations.bootstrap(session, settings.bootstrap_integrations)
        tasks = []
        if settings.workers_enabled:
            c = app.state.core
            tasks = [asyncio.create_task(_worker(c, "webhooks", events.deliver_pending, settings.worker_interval_s)),
                     asyncio.create_task(_worker(c, "jira", escalations.jira_pass, settings.worker_interval_s * 2)),
                     asyncio.create_task(_worker(c, "index-jobs", docs.follow_jobs, settings.worker_interval_s * 3))]
        yield
        for t in tasks:
            t.cancel()
        for t in tasks:
            with suppress(asyncio.CancelledError):
                await t
        await app.state.core.close()

    app = FastAPI(title="Platform core (admin)", version=__version__, lifespan=lifespan,
                  description="Открытый API для интеграций, сайт для владельцев, админов и ТП. Контракт: docs/API.md")
    errors.install(app)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                           allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.include_router(v1.router)
    app.include_router(panel.router)
    app.include_router(public.router)

    @app.get("/health", tags=["service"])
    async def health() -> dict:
        out = {"status": "ok", "version": __version__}
        try:
            async with db.sessionmaker()() as session:
                await session.execute(text("select 1"))
            out["database"] = "ok"
        except Exception:  # noqa: BLE001
            out["database"], out["status"] = "error", "degraded"
        try:
            # bounded: an absent RAG (e.g. the stack started without llm) must not stall the container's healthcheck —
            # resolving a missing host alone takes ~4 s in Docker's DNS, as long as the healthcheck waits
            rag = await asyncio.wait_for(app.state.core.rag.health(), timeout=2.0)
            out["rag"] = rag.get("status", "ok")
        except (RagError, RagUnavailable, TimeoutError):
            out["rag"], out["status"] = "unavailable", "degraded"
        return out

    return app


def app_factory() -> FastAPI:  # uvicorn admin_api.main:app_factory --factory
    return create_app()
