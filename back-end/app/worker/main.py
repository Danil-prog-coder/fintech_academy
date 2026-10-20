"""Процесс worker: python -m app.worker"""

import asyncio
import logging
import signal
from contextlib import AsyncExitStack, suppress

from app.core.config import get_settings
from app.core.runtime import build_services
from app.db import session as db_session
from app.worker.jobs import recover_stale, run_pending

log = logging.getLogger("app.worker")


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    db_session.init_engine()
    sessions = db_session._sessionmaker
    assert sessions is not None

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))

    async with AsyncExitStack() as stack:
        services = await build_services(stack, settings)
        if services.embeddings is None:
            log.warning("GigaChat не настроен: индексация невозможна, задачи ждут ключей.")
        log.info("worker started")
        while not stop.is_set():
            handled = 0
            if services.embeddings is not None:
                await recover_stale(sessions)
                handled = await run_pending(sessions, services)
            if handled == 0:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_sec)
    await db_session.dispose_engine()
    log.info("worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
