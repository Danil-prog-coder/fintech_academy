import json
import os
import secrets
from dataclasses import dataclass, field

import httpx
import pytest

os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(48))

from admin_api.core.config import Settings  # noqa: E402
from admin_api.core.runtime import build_core  # noqa: E402
from admin_api.db import session as db  # noqa: E402
from admin_api.db.session import Base  # noqa: E402
from admin_api.main import create_app  # noqa: E402
from admin_api.services import integrations  # noqa: E402

KEY_A = "ik_mail-demo_" + "a" * 40
KEY_B = "ik_other_" + "b" * 40


@dataclass
class FakeRag:
    """The hidden RAG service as the admin service sees it (httpx transport)."""

    calls: list = field(default_factory=list)
    answer: dict = field(default_factory=lambda: {"action": "answer", "text": "Ответ [1]", "formatted_text": "Ответ [1]",
                                                  "sources": [{"citation_label": "[1]", "document_title": "Док", "doc_id": "d",
                                                               "chunk_id": "d:0001", "url": "http://x/v1/public/rag/documents/d/view?sig=s"}],
                                                  "image_ids": ["d/img001.png"], "confidence": 0.9, "confidence_level": "high",
                                                  "usage": {"cost_usd": 0.01}, "trace": [1, 2]})
    jobs: dict = field(default_factory=dict)
    counter: int = 0

    def final(self, payload: dict) -> dict:
        self.counter += 1
        return {**self.answer, "request_id": f"req{self.counter:04d}", "session_id": payload.get("session_id")}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.headers.get("content-type", "").startswith("application/json") else None
        self.calls.append((method, path, body, dict(request.url.params), dict(request.headers), request.content))
        if path == "/ask/sync":
            return httpx.Response(200, json=self.final(body))
        if path == "/ask":
            fin = self.final(body)
            sse = (f"event: status\ndata: {json.dumps({'type': 'status', 'text': 'Ищу…'})}\n\n"
                   f"event: delta\ndata: {json.dumps({'type': 'delta', 'text': 'Отв'})}\n\n"
                   f"event: final\ndata: {json.dumps({'type': 'final', **fin}, ensure_ascii=False)}\n\n")
            return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})
        if path in ("/feedback", "/knowledge"):
            return httpx.Response(200, json={"ok": True, "job": {"job_id": "kjob1", "status": "queued"}, "file": "f.md"})
        if path.startswith("/sessions/"):
            return httpx.Response(200, json={"ok": True})
        if path == "/documents" and method == "POST":
            return httpx.Response(200, json={"saved": ["a.md"], "job": {"job_id": "job1", "status": "queued"}})
        if path == "/documents" and method == "GET":
            return httpx.Response(200, json={"documents": [{"doc_id": "a", "title": "A", "section": "general"}]})
        if path == "/documents/staged":
            return httpx.Response(200, json={"files": [{"name": "a.md", "section": "general"}]})
        if path == "/jobs":
            return httpx.Response(200, json={"jobs": list(self.jobs.values())})
        if path.startswith("/images/"):
            return httpx.Response(200, content=b"PNG", headers={"content-type": "image/png"})
        if path.startswith("/documents/") and path.endswith("/view"):
            if "authorization" in {k.lower() for k in request.headers}:
                return httpx.Response(500, text="token must not be forwarded")
            ok = request.url.params.get("sig") == "good"
            return httpx.Response(200 if ok else 401, text="<html>doc</html>" if ok else "no",
                                  headers={"content-type": "text/html"})
        if path == "/analytics/summary":
            return httpx.Response(200, json={"topics": {"x": 1}})
        if path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404, json={"detail": "not faked"})


@dataclass
class Outbox:
    """Captures outgoing webhooks and Jira calls."""

    requests: list = field(default_factory=list)
    status: int = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={})


class FakeJira:
    def __init__(self):
        self.issues: dict[str, dict] = {}
        self.comments: list[tuple[str, str]] = []
        self.transitions: list[tuple[str, str]] = []
        self.fail = False

    def __call__(self, cfg):
        return self

    async def check(self):
        return {"key": "SUP", "name": "Support"}

    async def create_issue(self, summary, description, labels, priority, idempotency_key):
        from admin_api.services.jira import JiraError
        if self.fail:
            raise JiraError("down")
        for k, v in self.issues.items():
            if v["idem"] == idempotency_key:
                return k
        key = f"SUP-{len(self.issues) + 1}"
        self.issues[key] = {"summary": summary, "description": description, "idem": idempotency_key}
        return key

    async def add_comment(self, key, text):
        self.comments.append((key, text))
        return str(len(self.comments) + 100)

    async def transition(self, key, status):
        self.transitions.append((key, status))
        return True


@pytest.fixture
async def env(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path}/t.db"  # Postgres: set TEST_DATABASE_URL
    settings = Settings(database_url=url, workers_enabled=False,
                        panel_public_url="https://panel.test", api_public_url="https://api.test",
                        webhook_allow_private=True, rag_url="http://rag", rag_api_token="tok")
    rag, out, jira = FakeRag(), Outbox(), FakeJira()
    db.init_engine(settings.database_url)
    async with db.engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    core = build_core(settings, rag_transport=httpx.MockTransport(rag.handler), http_transport=httpx.MockTransport(out.handler))
    core.jira_factory = jira
    app = create_app(settings, core=core)
    app.state.core = core
    async with db.sessionmaker()() as s:
        await integrations.create(s, "mail-demo", "Почта-демо", KEY_A)
        await integrations.create(s, "other", "Другая", KEY_B)
        await s.commit()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.test")

    class Env:
        pass

    e = Env()
    e.app, e.client, e.rag, e.out, e.jira, e.core, e.settings = app, client, rag, out, jira, core, settings
    e.h = {"X-Api-Key": KEY_A}
    e.hb = {"X-Api-Key": KEY_B}
    yield e
    await client.aclose()
    await core.close()
    await db.dispose()


async def create_project(e, owner="u-owner", login="owner"):
    r = await e.client.post("/v1/projects", headers=e.h, json={"name": "Проект X", "owner_external_id": owner,
                                                               "owner_login": login, "owner_display_name": "Оля"})
    assert r.status_code == 201, r.text
    return r.json()


PW = "correct-horse-battery"
CSRF = {"X-Requested-With": "panel"}


def new_client(e) -> httpx.AsyncClient:
    """Another browser: its own cookie jar."""
    return httpx.AsyncClient(transport=e.client._transport, base_url="https://api.test")


async def register(client, login, password=PW):
    r = await client.post("/panel/api/auth/register", headers=CSRF, json={"login": login, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


async def set_password(e, setup_url, password=PW, login=None):
    """The person from a link of an integration: registers a site account (login — the hint from the link) and attaches
    the access to it. Happens in his own browser, so the caller's cookies stay as they were."""
    token = setup_url.split("token=", 1)[1]
    async with new_client(e) as browser:
        info = (await browser.get("/panel/api/auth/invite", params={"token": token})).json()
        await register(browser, login or info["login_hint"], password)
        r = await browser.post("/panel/api/auth/claim", headers=CSRF, json={"token": token})
        assert r.status_code == 200, r.text
    return password


async def panel_login(e, login, password, client=None):
    r = await (client or e.client).post("/panel/api/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return dict(CSRF)
