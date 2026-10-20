import logging
import time
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, Request

from app.api import auth, feedback, mail, mailbox, qa, repo, webhook
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.runtime import build_services
from app.db.session import dispose_engine, init_engine

access_log = logging.getLogger("app.access")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()  # падаем на старте, если нет обязательных переменных
    logging.basicConfig(level=settings.log_level)
    init_engine()
    async with AsyncExitStack() as stack:
        services = await build_services(stack, settings)
        # Без ключей приложение стартует; LLM-эндпоинты отвечают 503 llm_not_configured.
        app.state.github = services.github
        app.state.llm = services.llm
        app.state.embeddings = services.embeddings
        yield
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="Решено", lifespan=lifespan)
    install_error_handlers(app)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        # Только маршрут и код: ни query-строки, ни тел запросов в журнале нет (NFR-04).
        access_log.info(
            "%s %s -> %s %.0f ms",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    for module in (auth, repo, qa, mail, mailbox, feedback, webhook):
        app.include_router(module.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
