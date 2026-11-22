"""End-to-end environment of the mail demo.

The real application with its lifespan and a real database (a sqlite file per test). The platform (admin service)
is faked at the HTTP level — `FakePlatform` answers the /v1 calls the demo makes and records them; mail servers are
real local IMAP/SMTP servers (tests/fake_mail.py). Tests call the API over HTTP, like the frontend does.
"""

import json
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789-abcdefghij")
os.environ.setdefault("ENCRYPTION_KEY", "Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm8=")

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from mail_api.core import ratelimit
from mail_api.core.config import get_settings
from mail_api.db import session as db_session
from mail_api.db.models import Base
from mail_api.main import create_app
from mail_api.services.platform import PlatformClient

ERROR_KEYS = {"code", "message", "retryable"}
PLATFORM_KEY = "ik_mail-demo_" + "k" * 40


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_error(response, status: int, code: str, retryable: bool = False) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == ERROR_KEYS and body["code"] == code and body["retryable"] is retryable
    assert body["message"]


@dataclass
class FakePlatform:
    """The platform's open API as the demo sees it: projects, statuses, answers, tickets, events."""

    calls: list = field(default_factory=list)
    projects: dict = field(default_factory=dict)  # id -> {"name", "members": {ext: role}}
    events: list = field(default_factory=list)
    action: str = "answer"
    down: bool = False

    def _err(self, status: int, code: str, message: str = "ошибка") -> httpx.Response:
        return httpx.Response(status, json={"code": code, "message": message, "retryable": False})

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("platform down")
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else None
        self.calls.append((method, path, body, dict(request.url.params), request.headers.get("x-api-key")))
        if request.headers.get("x-api-key") != PLATFORM_KEY:
            return self._err(401, "unauthorized")
        if path == "/v1/projects" and method == "POST":
            pid = f"{len(self.projects) + 1:08x}"
            self.projects[pid] = {"name": body["name"], "members": {body["owner_external_id"]: "owner"}}
            return httpx.Response(201, json={"project": {"id": pid, "name": body["name"], "role": "owner", "created_at": "t"},
                                             "project_code": f"{pid}-{'s' * 24}",
                                             "owner_panel_setup_url": "https://panel.test/setup?token=abc"})
        if path == "/v1/projects" and method == "GET":
            ext = request.url.params.get("external_id")
            return httpx.Response(200, json={"projects": [{"id": pid, "name": p["name"], "role": p["members"][ext], "created_at": "t"}
                                                          for pid, p in self.projects.items() if ext in p["members"]]})
        if path == "/v1/events":
            after = int(request.url.params.get("after", 0))
            return httpx.Response(200, json={"events": [e for e in self.events if e["id"] > after]})
        m = re.match(r"^/v1/projects/(\w+)(/.*)?$", path)
        if not m or m.group(1) not in self.projects:
            return self._err(404, "project_not_found")
        pid, rest, proj = m.group(1), m.group(2) or "", self.projects[m.group(1)]
        if rest == "/members" and method == "GET":
            return httpx.Response(200, json={"members": [{"external_id": e, "role": r} for e, r in proj["members"].items()]})
        if rest == "/sections":
            return httpx.Response(200, json={"sections": [{"slug": "general", "title": "Общее"}]})
        mm = re.match(r"^/members/([^/]+)$", rest)
        if mm and method == "PUT":
            if proj["members"].get(body["acting_external_id"]) != "owner":
                return self._err(403, "owner_only", "Только владелец")
            proj["members"][mm.group(1)] = body["role"]
            out = {"member": {"external_id": mm.group(1), "role": body["role"]}}
            if body["role"] in ("admin", "support"):
                out["panel_setup_url"] = "https://panel.test/setup?token=new"
            return httpx.Response(200, json=out)
        if mm and method == "DELETE":
            proj["members"].pop(mm.group(1), None)
            return httpx.Response(204)
        if rest == "/ask":
            if body["external_id"] not in proj["members"]:
                return self._err(403, "not_a_member", "Пользователь не состоит в проекте")
            return httpx.Response(200, json={"request_id": f"r{len(self.calls)}", "action": self.action,
                                             "text": f"Ответ на: {body['message'].splitlines()[0]}",
                                             "sources": [{"citation_label": "[1]", "document_title": "Регламент", "section_path": "1",
                                                          "excerpt": "цитата", "url": "https://x/doc"}],
                                             "confidence_level": "high"})
        if rest == "/feedback":
            return httpx.Response(200, json={"ok": True})
        if rest == "/escalations" and method == "POST":
            return httpx.Response(201, json={"key": "ESC-1", "status": "waiting", "messages": []})
        if rest.startswith("/escalations"):
            return httpx.Response(200, json={"escalations": []} if rest == "/escalations" else {"key": "ESC-1", "messages": []})
        return self._err(404, "not_faked")


@dataclass
class World:
    client: AsyncClient
    app: object
    platform: FakePlatform

    async def register(self, email: str = "dev@example.com", password: str = "correct-horse"):
        r = await self.client.post("/auth/register", json={"email": email, "password": password})
        assert r.status_code == 201, r.text
        return r.json()

    async def user(self, email: str = "dev@example.com") -> dict[str, str]:
        return bearer((await self.register(email))["access_token"])

    async def rows(self, model) -> list:
        async with db_session._sessionmaker() as s:
            return list((await s.scalars(select(model))).all())


@asynccontextmanager
async def open_world(monkeypatch: pytest.MonkeyPatch, tmp_path, *, mail_private: bool = True, rate_limit: bool = False,
                     platform_key: str = PLATFORM_KEY):
    db_path = tmp_path / f"e2e-{time.monotonic_ns()}.db"
    env = {
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}",
        "SECRET_KEY": "test-secret-key-0123456789-abcdefghij",
        "ENCRYPTION_KEY": "Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm8=",
        "PLATFORM_URL": "http://platform.test",
        "PLATFORM_API_KEY": platform_key,
        "MAIL_ALLOW_PRIVATE_HOSTS": "true" if mail_private else "false",
        "MAIL_TIMEOUT_SEC": "5",
        "RATE_LIMIT_ENABLED": "true" if rate_limit else "false",
        "LOG_LEVEL": "WARNING",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    ratelimit.reset()
    pg_url = os.environ.get("E2E_DATABASE_URL")  # postgresql+asyncpg://… — the same tests on PostgreSQL
    if pg_url:
        env["DATABASE_URL"] = pg_url
        monkeypatch.setenv("DATABASE_URL", pg_url)
    engine = create_async_engine(env["DATABASE_URL"])
    async with engine.begin() as conn:
        if pg_url:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    fake = FakePlatform()
    client = PlatformClient("http://platform.test", platform_key, transport=httpx.MockTransport(fake.handle))
    db_session._sessionmaker = None
    app = create_app(platform_client=client, start_poller=False)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=bool(os.environ.get("E2E_RAISE")))
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield World(client=http, app=app, platform=fake)
    db_session._sessionmaker = None
    get_settings.cache_clear()
    ratelimit.reset()


@pytest_asyncio.fixture
async def mail():
    """Local IMAP and SMTP servers with one mailbox."""
    from tests.fake_mail import FakeMail

    server = await FakeMail().start()
    yield server
    await server.stop()


@pytest_asyncio.fixture
async def world(monkeypatch, tmp_path):
    async with open_world(monkeypatch, tmp_path) as w:
        yield w
