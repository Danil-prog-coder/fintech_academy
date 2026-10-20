"""Окружение для сквозных (e2e) тестов.

Поднимается настоящее приложение вместе с lifespan, настоящая БД (sqlite-файл на тест) и
настоящие клиенты GitHub, GigaChat и YandexGPT. Мокается только сеть: HTTP-ответы внешних
сервисов отдаёт respx (см. fakes.py), а индексацию выполняет настоящий worker
(`world.run_worker()`). Тесты ходят в API по HTTP, как фронтенд и расширение.
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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import ratelimit
from app.core.config import get_settings
from app.core.runtime import Services
from app.db import session as db_session
from app.db.models import Base
from app.main import create_app
from app.worker.jobs import run_pending
from tests.fakes import SCOPE_MARK, FakeGitHub, chat_reply, embed

AUTH_URL = "https://auth.test/oauth"
LLM_URL = "https://llm.test/v1"
YANDEX_URL = "https://yandex.test/foundationModels/v1"
WEBHOOK_SECRET = "hook-secret"
DEFAULT_REPO = "https://github.com/acme/project"


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
    github: FakeGitHub = field(default_factory=FakeGitHub)
    # режим GigaChat-чата и Yandex: normal | down (503) | garbage (мусор) | auth (403) | nojson
    llm_mode: str = "normal"
    yandex_mode: str = "normal"
    llm_calls: list[list[dict]] = field(default_factory=list)  # messages каждого запроса
    yandex_calls: list[list[dict]] = field(default_factory=list)
    embed_calls: list[list[str]] = field(default_factory=list)

    async def register(self, email: str = "dev@example.com", password: str = "correct-horse"):
        r = await self.client.post("/auth/register", json={"email": email, "password": password})
        assert r.status_code == 201, r.text
        return r.json()

    async def user(self, email: str = "dev@example.com") -> dict[str, str]:
        """Регистрирует пользователя, возвращает заголовок авторизации."""
        return bearer((await self.register(email))["access_token"])

    async def connect(self, headers, url=DEFAULT_REPO, **extra):
        return await self.client.post("/repo/connect", json={"url": url, **extra}, headers=headers)

    async def ready_user(self, email: str = "dev@example.com", url: str = DEFAULT_REPO, **extra):
        """Пользователь с подключённым и проиндексированным репозиторием."""
        h = await self.user(email)
        assert (await self.connect(h, url, **extra)).status_code == 201
        await self.run_worker()
        status = (await self.client.get("/repo/status", headers=h)).json()
        assert status["status"] == "ready", status
        return h

    async def run_worker(self) -> int:
        """Выполняет все готовые задачи очереди настоящим кодом worker."""
        state = self.app.state
        services = Services(github=state.github, llm=state.llm, embeddings=state.embeddings)
        return await run_pending(db_session._sessionmaker, services)

    async def rows(self, model) -> list:
        async with db_session._sessionmaker() as s:
            return list((await s.scalars(select(model))).all())

    async def push_event(
        self, sha: str, repo: str = "acme/project", ref: str = "refs/heads/main", **extra
    ):
        payload = {"repository": {"full_name": repo}, "after": sha, "ref": ref, **extra}
        return await self.webhook(payload)

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
        return [m for m in self.llm_calls if SCOPE_MARK in m[0]["content"]]

    def qa_prompts(self) -> list[list[dict]]:
        return [m for m in self.llm_calls if "<контекст>" in m[-1]["content"]]


def _llm_response(world: World, messages: list[dict], mode: str, shape: str) -> httpx.Response:
    if mode == "down":
        return httpx.Response(503)
    if mode == "auth":
        return httpx.Response(403)
    if mode in ("nosources", "badsources") and "<контекст>" in messages[-1]["content"]:
        # «Нейросеть» уверенно отвечает, но подтверждающих фрагментов не называет.
        sources = [] if mode == "nosources" else [99]
        text = json.dumps({"status": "answered", "answer": "Выдуманный ответ", "sources": sources})
    else:
        text = "абракадабра, а не JSON" if mode == "garbage" else chat_reply(messages)
    if shape == "yandex":
        return httpx.Response(
            200,
            json={
                "result": {
                    "alternatives": [
                        {"message": {"role": "assistant", "text": text}, "status": "FINAL"}
                    ],
                    "usage": {"inputTextTokens": "5", "completionTokens": "3"},
                }
            },
        )
    return httpx.Response(
        200,
        json={
            "model": "GigaChat:test",
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        },
    )


@asynccontextmanager
async def open_world(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    gigachat: bool = True,
    yandex: bool = False,
    webhook_secret: str = WEBHOOK_SECRET,
    mail_private: bool = True,
    rate_limit: bool = False,
):
    """Поднимает приложение целиком. gigachat=False — как на сервере без ключей."""
    db_path = tmp_path / f"e2e-{time.monotonic_ns()}.db"
    env = {
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}",
        "SECRET_KEY": "test-secret-key-0123456789-abcdefghij",
        "ENCRYPTION_KEY": "Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm8=",
        "GITHUB_WEBHOOK_SECRET": webhook_secret,
        "PUBLIC_BASE_URL": "https://resheno.example.com",
        "GIGACHAT_CREDENTIALS": "test-key" if gigachat else "",
        "GIGACHAT_AUTH_URL": AUTH_URL,
        "GIGACHAT_BASE_URL": LLM_URL,
        "GIGACHAT_CA_BUNDLE": "",
        "GIGACHAT_VERIFY_SSL": "true",
        "GIGACHAT_MAX_RETRIES": "0",
        "YANDEX_API_KEY": "yandex-key" if yandex else "",
        "YANDEX_FOLDER_ID": "folder" if yandex else "",
        "YANDEX_BASE_URL": YANDEX_URL,
        "QA_MIN_SIMILARITY": "0.08",
        "WORKER_RETRY_BASE_SEC": "0",
        "MAIL_ALLOW_PRIVATE_HOSTS": "true" if mail_private else "false",
        "MAIL_TIMEOUT_SEC": "5",
        "RATE_LIMIT_ENABLED": "true" if rate_limit else "false",
        "LOG_LEVEL": "WARNING",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    ratelimit.reset()

    # E2E_DATABASE_URL=postgresql+asyncpg://... прогоняет тесты на настоящем PostgreSQL + pgvector.
    pg_url = os.environ.get("E2E_DATABASE_URL")
    if pg_url:
        env["DATABASE_URL"] = pg_url
        monkeypatch.setenv("DATABASE_URL", pg_url)
    engine = create_async_engine(env["DATABASE_URL"])
    async with engine.begin() as conn:
        if pg_url:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    app = create_app()
    with respx.mock(assert_all_called=False) as router:
        world = World(client=None, app=app)  # type: ignore[arg-type]
        router.route(url__regex=r"https://api\.github\.com/.*").mock(side_effect=world.github.handle)
        router.post(AUTH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "tok", "expires_at": int((time.time() + 1800) * 1000)},
            )
        )

        def giga_chat(request: httpx.Request) -> httpx.Response:
            messages = json.loads(request.content)["messages"]
            world.llm_calls.append(messages)
            return _llm_response(world, messages, world.llm_mode, "gigachat")

        def giga_embed(request: httpx.Request) -> httpx.Response:
            texts = json.loads(request.content)["input"]
            world.embed_calls.append(texts)
            data = [{"index": i, "embedding": embed(t)} for i, t in enumerate(texts)]
            return httpx.Response(200, json={"data": data})

        def yandex_chat(request: httpx.Request) -> httpx.Response:
            raw = json.loads(request.content)["messages"]
            messages = [{"role": m["role"], "content": m["text"]} for m in raw]
            world.yandex_calls.append(messages)
            return _llm_response(world, messages, world.yandex_mode, "yandex")

        router.post(f"{LLM_URL}/chat/completions").mock(side_effect=giga_chat)
        router.post(f"{LLM_URL}/embeddings").mock(side_effect=giga_embed)
        router.post(f"{YANDEX_URL}/completion").mock(side_effect=yandex_chat)

        async with app.router.lifespan_context(app):
            # raise_app_exceptions=False: необработанная ошибка должна дойти до клиента как 500.
            transport = ASGITransport(app=app, raise_app_exceptions=bool(os.environ.get("E2E_RAISE")))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                world.client = client
                yield world
    get_settings.cache_clear()
    ratelimit.reset()


@pytest_asyncio.fixture
async def mail():
    """Локальные IMAP и SMTP серверы с одним ящиком."""
    from tests.fake_mail import FakeMail

    server = await FakeMail().start()
    yield server
    await server.stop()


@pytest_asyncio.fixture
async def world(monkeypatch, tmp_path):
    async with open_world(monkeypatch, tmp_path) as w:
        yield w
