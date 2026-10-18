import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.db.session import dispose_engine, init_engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()  # падаем на старте, если нет обязательных переменных
    logging.basicConfig(level=settings.log_level)
    init_engine()
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="Решено", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(auth.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
