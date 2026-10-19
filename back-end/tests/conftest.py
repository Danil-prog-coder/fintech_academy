"""Окружение для сквозных (e2e) тестов.

Поднимается настоящее приложение вместе с lifespan, настоящая БД (sqlite-файл на тест) и
настоящие клиенты GitHub и GigaChat. Мокается только сеть: api.github.com и GigaChat
перехватывает respx, остальное — боевой код. Тесты ходят в API по HTTP, как фронтенд и
расширение, а в БД заглядывают только чтобы проверить хранимое или подменить воркера.
"""

import hashlib
import hmac
import json
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

# Значения по умолчанию на случай прямого импорта модулей приложения вне фикстур.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789-abcdefghij")
os.environ.setdefault("ENCRYPTION_KEY", "Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm8=")

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db import session as db_session
from app.db.models import Base, Repository
from app.main import create_app

AUTH_URL = "https://auth.test/oauth"
LLM_URL = "https://llm.test/v1"
WEBHOOK_SECRET = "hook-secret"
SCOPE_PROMPT_MARK = "фильтр запросов"  # узнаём запрос проверки «вопрос по проекту?»
OFFTOPIC_WORDS = ("погод", "борщ")  # их «нейросеть» считает посторонними


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def sign(payload: dict, secret: str = WEBHOOK_SECRET) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    return body, "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@dataclass
class World:
    """Запущенное приложение + управляемые «внешние» сервисы."""

    client: AsyncClient
    app: object
    # режим GigaChat: normal | down (503) | garbage (мусор вместо JSON) | auth (403)
    llm_mode: str = "normal"
    llm_calls: list[list[dict]] = field(default_factory=list)  # messages каждого запроса
    github_calls: list[httpx.Request] = field(default_factory=list)
    github_failure: str | None = None  # "5xx" | "network"

    async def register(self, email: str = "dev@example.com", password: str = "correct-horse"):
        r = await self.client.post("/auth/register", json={"email": email, "password": password})
        assert r.status_code == 201, r.text
        return r.json()

    async def user(self, email: str = "dev@example.com") -> dict[str, str]:
        """Регистрирует пользователя, возвращает заголовок авторизации."""
        return bearer((await self.register(email))["access_token"])

    async def connect(self, headers, url="https://github.com/acme/project", **extra):
        return await self.client.post("/repo/connect", json={"url": url, **extra}, headers=headers)

    async def finish_indexing(self, commit: str = "abc123", status: str = "ready") -> None:
        """Роль воркера: индексатора в проекте пока нет, поэтому статус ставим вручную."""
        async with db_session._sessionmaker() as s:
            await s.execute(update(Repository).values(status=status, last_commit=commit))
            await s.commit()

    async def rows(self, model) -> list:
        async with db_session._sessionmaker() as s:
            return list((await s.scalars(select(model))).all())

    async def webhook(self, payload: dict, event: str = "push", signature: str | None = None):
        body, sig = sign(payload)
        return await self.client.post(
            "/github/webhook",
            content=body,
            headers={
                "X-GitHub-Event": event,
                "X-Hub-Signature-256": sig if signature is None else signature,
                "Content-Type": "application/json",
            },
        )

    def scope_checks(self) -> list[list[dict]]:
        return [m for m in self.llm_calls if SCOPE_PROMPT_MARK in m[0]["content"]]


def _github_handler(world: World):
    def handler(request: httpx.Request) -> httpx.Response:
        world.github_calls.append(request)
        if world.github_failure == "network":
            raise httpx.ConnectError("boom", request=request)
        if world.github_failure == "5xx":
            return httpx.Response(502)
        auth = request.headers.get("Authorization")
        repo = request.url.path.removeprefix("/repos/")
        if auth == "Bearer bad":
            return httpx.Response(401)
        if repo.startswith("acme/secret") and auth != "Bearer ghp_secret":
            return httpx.Response(404)  # приватный репозиторий без доступа
        return httpx.Response(200, json={"default_branch": "main", "private": auth is not None})

    return handler


def _gigachat_handler(world: World):
    def chat(request: httpx.Request) -> httpx.Response:
        messages = json.loads(request.content)["messages"]
        world.llm_calls.append(messages)
        if world.llm_mode == "down":
            return httpx.Response(503)
        if world.llm_mode == "auth":
            return httpx.Response(403)
        if world.llm_mode == "garbage":
            text = "абракадабра"
        else:
            question = messages[-1]["content"].lower()
            offtopic = any(w in question for w in OFFTOPIC_WORDS)
            text = json.dumps({"in_scope": not offtopic})
        return httpx.Response(
            200,
            json={
                "model": "GigaChat:test",
                "choices": [{"message": {"role": "assistant", "content": text}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
        )

    return chat


@asynccontextmanager
async def open_world(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    gigachat: bool = True,
    webhook_secret: str = WEBHOOK_SECRET,
):
    """Поднимает приложение целиком. gigachat=False — как на сервере без ключей."""
    db_path = tmp_path / f"e2e-{time.monotonic_ns()}.db"
    env = {
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}",
        "SECRET_KEY": "test-secret-key-0123456789-abcdefghij",
        "ENCRYPTION_KEY": "Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm8=",
        "GITHUB_WEBHOOK_SECRET": webhook_secret,
        "GIGACHAT_CREDENTIALS": "test-key" if gigachat else "",
        "GIGACHAT_AUTH_URL": AUTH_URL,
        "GIGACHAT_BASE_URL": LLM_URL,
        "GIGACHAT_CA_BUNDLE": "",
        "GIGACHAT_VERIFY_SSL": "true",
        "GIGACHAT_MAX_RETRIES": "0",
        "LOG_LEVEL": "WARNING",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()

    engine = create_async_engine(env["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    app = create_app()
    with respx.mock(assert_all_called=False) as router:
        world = World(client=None, app=app)  # type: ignore[arg-type]
        router.get(url__regex=r"https://api\.github\.com/repos/.*").mock(
            side_effect=_github_handler(world)
        )
        router.post(AUTH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "tok", "expires_at": int((time.time() + 1800) * 1000)},
            )
        )
        router.post(f"{LLM_URL}/chat/completions").mock(side_effect=_gigachat_handler(world))

        async with app.router.lifespan_context(app):
            # raise_app_exceptions=False: необработанная ошибка должна дойти до клиента как 500.
            transport = ASGITransport(app=app, raise_app_exceptions=bool(os.environ.get("E2E_RAISE")))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                world.client = client
                yield world
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def world(monkeypatch, tmp_path):
    async with open_world(monkeypatch, tmp_path) as w:
        yield w
