import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789-abcdefghij")
os.environ.setdefault("ENCRYPTION_KEY", "Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm8=")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "hook-secret")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.errors import AppError
from app.db import session as db_session
from app.db.models import Base, Repository
from app.main import create_app
from app.services.github import RepoInfo, get_github


class FakeGitHub:
    """Подмена GitHubClient: доступ есть, если токен не равен 'bad'."""

    async def check_access(self, owner, name, token):
        if token == "bad":
            raise AppError("repo_no_access", "Репозиторий не найден.", 400)
        return RepoInfo(default_branch="main", private=token is not None)


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    db_session._engine = engine
    db_session._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()
    app.dependency_overrides[get_github] = lambda: FakeGitHub()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def register(client, email="user@example.com", password="correct-horse"):
    r = await client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def set_repo_status(status: str, last_commit: str | None = None):
    async with db_session._sessionmaker() as s:
        await s.execute(update(Repository).values(status=status, last_commit=last_commit))
        await s.commit()
