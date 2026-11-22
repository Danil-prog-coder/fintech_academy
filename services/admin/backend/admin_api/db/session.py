"""Database engine, sessions and the common declarative base."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    MetaData,
    TypeDecorator,
    event,
    select,  # noqa: F401  (re-exported for tests and workers)
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Timestamps are stored and returned in UTC with tzinfo (SQLite used in tests drops the offset)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str) -> AsyncEngine:
    global _engine, _sessionmaker
    kwargs = {"pool_pre_ping": True} if not url.startswith("sqlite") else {}
    _engine = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(_engine.sync_engine, "connect")
        def _fk_on(dbapi_conn, _record):  # SQLite enforces ON DELETE CASCADE only with this pragma
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("database engine is not initialised")
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("database engine is not initialised")
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        yield session


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = _sessionmaker = None
