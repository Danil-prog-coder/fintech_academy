from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str | None = None) -> None:
    global _engine, _sessionmaker
    _engine = create_async_engine(url or get_settings().database_url)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


async def dispose_engine() -> None:
    if _engine is not None:
        await _engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    assert _sessionmaker is not None, "engine не инициализирован"
    async with _sessionmaker() as session:
        yield session
