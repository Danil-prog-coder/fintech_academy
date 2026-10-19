import logging
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api import auth, feedback, mail, qa, repo, webhook
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.db.session import dispose_engine, init_engine
from app.llm.gigachat import build_gigachat, make_http_client
from app.services.github import GitHubClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()  # падаем на старте, если нет обязательных переменных
    logging.basicConfig(level=settings.log_level)
    init_engine()
    async with AsyncExitStack() as stack:
        github_http = await stack.enter_async_context(
            httpx.AsyncClient(timeout=settings.llm_timeout_sec)
        )
        app.state.github = GitHubClient(github_http)

        # Без ключей приложение стартует; LLM-зависимости ответят 503 llm_not_configured.
        if settings.gigachat_credentials:
            giga_http = await stack.enter_async_context(make_http_client(settings))
            app.state.llm, app.state.embeddings = build_gigachat(settings, giga_http)
        yield
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="Решено", lifespan=lifespan)
    install_error_handlers(app)
    for module in (auth, repo, qa, mail, feedback, webhook):
        app.include_router(module.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
