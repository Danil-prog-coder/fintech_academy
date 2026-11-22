"""Mail demo: an IMAP/SMTP mail client with its own users that integrates the platform through its open API.

Nothing here talks to the RAG or knows how answers are made: questions, projects, statuses and support tickets go
to the platform (`/v1`), and its events come back by polling. Any messenger or portal can integrate the same way.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request

from mail_api.api import auth, mail, mailbox, platform
from mail_api.core.config import get_settings
from mail_api.core.errors import install_error_handlers
from mail_api.db import session as db
from mail_api.db.session import dispose_engine, init_engine
from mail_api.services import notifications
from mail_api.services.platform import PlatformClient

access_log = logging.getLogger("mail_api.access")


def create_app(platform_client: PlatformClient | None = None, start_poller: bool | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = get_settings()  # fail at start if required variables are missing
        logging.basicConfig(level=settings.log_level)
        if db._sessionmaker is None:
            init_engine()
        app.state.platform = platform_client or PlatformClient(settings.platform_url, settings.platform_api_key,
                                                               settings.platform_timeout_sec)
        task = None
        poll = settings.events_enabled if start_poller is None else start_poller
        if poll and app.state.platform.configured:
            task = asyncio.create_task(notifications.run_poller(app.state.platform, db._sessionmaker, settings.events_poll_sec))
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await app.state.platform.close()
        await dispose_engine()

    app = FastAPI(title="Почта (демо-интеграция платформы)", lifespan=lifespan)
    install_error_handlers(app)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        # route and status only: no query strings and no bodies in the log
        access_log.info("%s %s -> %s %.0f ms", request.method, request.url.path, response.status_code,
                        (time.perf_counter() - started) * 1000)
        return response

    for module in (auth, mail, mailbox, platform):
        app.include_router(module.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
