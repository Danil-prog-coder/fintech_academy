"""Применяет миграции БД. Запускается перед стартом API: python -m scripts.migrate

Если база создана старой версией проекта (таблицы есть, а alembic_version нет), она сначала
приводится к текущей схеме без потери данных: добавляются недостающие таблицы и столбцы,
после чего ей присваивается текущая ревизия.
"""

import asyncio
import sys

from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.config import get_settings
from app.db.models import Base

# Столбцы, появившиеся после первых версий схемы (create_all существующие таблицы не меняет).
LEGACY_COLUMNS = [
    ("repositories", "default_branch", "VARCHAR(255)"),
    ("repositories", "active_index_id", "INTEGER"),
    ("repositories", "last_error", "VARCHAR(60)"),
    ("repositories", "indexed_files", "INTEGER NOT NULL DEFAULT 0"),
    ("repositories", "skipped_files", "INTEGER NOT NULL DEFAULT 0"),
    ("jobs", "run_after", "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()"),
    ("jobs", "started_at", "TIMESTAMP WITH TIME ZONE"),
]


def _is_legacy(conn: Connection) -> bool:
    tables = set(inspect(conn).get_table_names())
    return "users" in tables and "alembic_version" not in tables


def _upgrade_legacy(conn: Connection) -> None:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(conn, checkfirst=True)
    for table, column, ddl in LEGACY_COLUMNS:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}"))
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_chunks_embedding "
            "ON chunks USING hnsw (embedding vector_cosine_ops)"
        )
    )


async def prepare() -> bool:
    """Приводит старую базу к текущей схеме. True, если база была старой."""
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        legacy = await conn.run_sync(_is_legacy)
        if legacy:
            print("migrate: найдена база старой версии, привожу к текущей схеме", flush=True)
            await conn.run_sync(_upgrade_legacy)
    await engine.dispose()
    return legacy


def main() -> None:
    legacy = asyncio.run(prepare())
    config = Config("alembic.ini")
    if legacy:
        command.stamp(config, "head")
    else:
        command.upgrade(config, "head")
    print("migrate: ok", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"migrate: ошибка {type(exc).__name__}", file=sys.stderr)
        raise
