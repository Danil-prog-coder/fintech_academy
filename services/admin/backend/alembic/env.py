"""Migrations run against DATABASE_URL (async driver); schema changes go only through Alembic."""

import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from admin_api import models  # noqa: F401  (registers the tables)
from admin_api.db import Base

target_metadata = Base.metadata


def _url() -> str:
    return os.environ.get("DATABASE_URL") or context.config.get_main_option("sqlalchemy.url")


def run_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
