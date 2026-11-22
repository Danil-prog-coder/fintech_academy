"""End-to-end: the three real services wired over HTTP in one process, no network and no model keys.

    mail (demo integration) ──/v1──► admin (platform core) ──internal API──► llm (RAG)

Real code everywhere: the RAG indexes a real document into an embedded Qdrant and runs its agent loop with hybrid
search and citation guardrails; admin enforces statuses and keeps tickets and events; mail talks to the platform
only through the open API. Two things are faked: the embedding model (deterministic bag-of-words) and the chat model
(a script that cites the top pre-search fragment when the question's words are in it, and otherwise says the
documentation has no answer). Run: make -C tests/e2e test (creates its own venv with the three services).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import tempfile
import time
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

TMP = tempfile.mkdtemp(prefix="platform-e2e-")
INTEGRATION_KEY = "ik_mail-demo_" + secrets.token_urlsafe(32)

# ---------------------------------------------------------------- llm environment (its settings are read first)
os.environ.update({
    "STATE_DIR": f"{TMP}/llm/var", "KB_DIR": f"{TMP}/llm/var/uploads", "QDRANT_PATH": f"{TMP}/llm/qdrant",
    "QDRANT_URL": "", "REDIS_URL": "", "DATABASE_URL": "", "ADMIN_API_TOKEN": "rag-token", "SERVICE_API_TOKEN": "",
    "DOC_LINK_SECRET": "doc-secret", "PUBLIC_BASE_URL": "https://platform.test/v1/public/rag",
    "LLM_PROVIDER": "openai", "LLM_API_KEY": "fake", "RERANK_MODE": "none", "FAQ_ENABLED": "false",
    "CLASSIFY_INTERVAL_S": "0", "QUESTIONS_ENABLED": "false", "GUARD_ENABLED": "false", "AGENT_STREAMING": "false",
    "MIN_EVIDENCE_SCORE": "0.05", "QUESTION_FALLBACK_EMBEDDER": "", "AUTO_INDEX_ON_START": "false",
    "SUPPORT_HOURS": "mon-sun 00:00-23:59", "ANSWER_CACHE_ENABLED": "false", "ROUTING_ENABLED": "false",
    "LLM_STALL_TIMEOUT_S": "0", "LLM_DEADLINE_CAP": "false", "RETRIEVAL_DENSE_TIMEOUT_S": "0", "RERANK_HEDGE_AFTER_S": "0",
})

import rag_service.agent.loop as rag_loop  # noqa: E402
import rag_service.api.app as rag_app  # noqa: E402
from rag_service.config import get_settings as rag_settings  # noqa: E402
from rag_service.index import embeddings as rag_embeddings  # noqa: E402
from rag_service.ingest import pipeline as rag_pipeline  # noqa: E402
from rag_service.retrieval import search as rag_search  # noqa: E402

rag_settings()  # cached before the other services change DATABASE_URL

# ---------------------------------------------------------------- admin and mail
from admin_api import db as admin_db  # noqa: E402
from admin_api.config import Settings as AdminSettings  # noqa: E402
from admin_api.core import build_core  # noqa: E402
from admin_api.db import Base as AdminBase  # noqa: E402
from admin_api.main import create_app as create_admin  # noqa: E402
from admin_api.services import docs as admin_docs  # noqa: E402
from admin_api.services import events as admin_events  # noqa: E402
from admin_api.services import integrations as admin_integrations  # noqa: E402

os.environ.update({"DATABASE_URL": f"sqlite+aiosqlite:///{TMP}/mail.db", "SECRET_KEY": "mail-secret-key-0123456789-abcdefgh",
                   "ENCRYPTION_KEY": "Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm8=", "PLATFORM_API_KEY": INTEGRATION_KEY,
                   "PLATFORM_URL": "https://platform.test", "RATE_LIMIT_ENABLED": "false"})

from mail_api.core.config import get_settings as mail_settings  # noqa: E402
from mail_api.db import session as mail_db  # noqa: E402
from mail_api.db.models import Base as MailBase  # noqa: E402
from mail_api.main import create_app as create_mail  # noqa: E402
from mail_api.services import notifications as mail_notifications  # noqa: E402
from mail_api.services.platform import PlatformClient  # noqa: E402

DOC = """# Регламент отпусков

## 1 Оформление отпуска

Заявление на отпуск оформляется в кадровом портале за две недели до начала отпуска.
Согласует отпуск руководитель отдела.

## 2 Перенос отпуска

Перенос отпуска согласуется с отделом кадров по служебной записке.
"""


# ---------------------------------------------------------------- fake models
def _vec(text: str) -> list[float]:
    v = np.zeros(256, dtype=np.float32)
    for w in re.findall(r"[а-яёa-z0-9]{4,}", text.lower()):
        v[int(hashlib.md5(w[:6].encode()).hexdigest(), 16) % 256] += 1.0
    n = float(np.linalg.norm(v)) or 1.0
    return (v / n).tolist()


class FakeEmbedder:
    model = "fake-bow"
    is_e5 = False

    def embed_documents(self, texts):
        return [_vec(t) for t in texts]

    def embed_query(self, text, **_):
        return _vec(text)


def _call(name: str, args: dict):
    fn = SimpleNamespace(name=name, arguments=json.dumps(args, ensure_ascii=False))
    return SimpleNamespace(id="c1", function=fn, type="function")


CALLS: list = []


def fake_chat(**kw):
    """The agent's model: answer from the first pre-search fragment that shares a word with the question."""
    messages = kw["messages"]
    CALLS.append([m.get("content")[:300] if isinstance(m.get("content"), str) else m for m in messages])
    question = next(m["content"] for m in reversed(messages) if m["role"] == "user" and isinstance(m["content"], str))
    found = [m["content"] for m in messages if m["role"] in ("system", "tool") and isinstance(m.get("content"), str)
             and re.search(r"^\[S\d+\]", m["content"], re.M)]
    if not found:  # first step: search the documentation (the real tool runs: hybrid search over Qdrant)
        msg = SimpleNamespace(content="", tool_calls=[_call("search_docs", {"query": question})],
                              model_dump=lambda **k: {"role": "assistant", "content": ""})
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                               _model_used="fake")
    pre = "\n\n".join(found)
    words = {w[:6] for w in re.findall(r"[а-яё]{5,}", question.lower())}
    for sid, body in re.findall(r"^\[(S\d+)\][^\n]*\n(.+?)(?=\n\n\[S|\Z)", pre, re.S | re.M):
        text = " ".join(body.split())
        if words & {w[:6] for w in re.findall(r"[а-яё]{5,}", text.lower())}:
            quote = " ".join(text.split()[:7])
            call = _call("final_answer", {"kind": "grounded", "coverage": "full", "image_ids": [],
                                          "citations": [{"n": 1, "source_id": sid, "quote": quote}], "text": f"{quote} [1]."})
            break
    else:
        call = _call("offer_operator", {"reason": "no_answer_in_docs"})
    msg = SimpleNamespace(content="", tool_calls=[call], model_dump=lambda **k: {"role": "assistant", "content": ""})
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                           _model_used="fake")


# ---------------------------------------------------------------- the wired platform
@pytest.fixture
async def platform(monkeypatch):
    monkeypatch.setattr(rag_pipeline, "get_embedder", FakeEmbedder)
    monkeypatch.setattr(rag_search, "get_embedder", FakeEmbedder)
    monkeypatch.setattr(rag_embeddings, "get_embedder", FakeEmbedder)
    monkeypatch.setattr(rag_loop, "chat", fake_chat)

    admin_settings = AdminSettings(database_url=f"sqlite+aiosqlite:///{TMP}/admin.db", secret_key="admin-" + "k" * 40,
                                   workers_enabled=False, rag_url="http://llm", rag_api_token="rag-token",
                                   panel_public_url="https://platform.test", api_public_url="https://platform.test")
    admin_db.init_engine(admin_settings.database_url)
    async with admin_db.engine().begin() as conn:
        await conn.run_sync(AdminBase.metadata.drop_all)
        await conn.run_sync(AdminBase.metadata.create_all)
    core = build_core(admin_settings, rag_transport=httpx.ASGITransport(app=rag_app.app))
    admin = create_admin(admin_settings, core=core)
    admin.state.core = core
    async with admin_db.sessionmaker()() as s:
        await admin_integrations.create(s, "mail-demo", "Почта (демо)", INTEGRATION_KEY)
        await s.commit()

    mail_settings.cache_clear()
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(mail_settings().database_url)
    async with engine.begin() as conn:
        await conn.run_sync(MailBase.metadata.drop_all)
        await conn.run_sync(MailBase.metadata.create_all)
    await engine.dispose()
    mail_db._sessionmaker = None
    platform_client = PlatformClient("https://platform.test", INTEGRATION_KEY, transport=httpx.ASGITransport(app=admin))
    mail = create_mail(platform_client=platform_client, start_poller=False)
    async with mail.router.lifespan_context(mail):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mail), base_url="https://mail.test") as m, \
                httpx.AsyncClient(transport=httpx.ASGITransport(app=admin), base_url="https://platform.test") as a:
            yield SimpleNamespace(mail=m, admin=a, core=core, platform_client=platform_client)
    await core.close()
    await admin_db.dispose()


async def _wait_rag_jobs(project_rag_id: str, timeout: float = 60) -> None:
    from rag_service import jobs as rag_jobs
    t0 = time.time()
    while time.time() - t0 < timeout:
        running = [j for j in rag_jobs.recent(20, project_rag_id) if j["status"] in ("queued", "running")]
        if not running:
            return
        await asyncio.sleep(0.2)
    raise TimeoutError("indexing did not finish")


async def _register(mail: httpx.AsyncClient, email: str) -> dict:
    r = await mail.post("/auth/register", json={"email": email, "password": "correct-horse-battery"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_whole_platform(platform):
    m, a = platform.mail, platform.admin
    owner, colleague = await _register(m, "owner@corp.example.com"), await _register(m, "colleague@corp.example.com")

    # 1. A project is created from the mail; the owner gets the project code and a link for the site, registers there
    #    and the project is attached to his site account
    r = await m.post("/platform/projects", headers=owner, json={"name": "Отдел кадров", "login": "hr-owner"})
    assert r.status_code == 201, r.text
    created = r.json()
    pid, code = created["project"]["id"], created["project_code"]
    token = created["owner_panel_setup_url"].split("token=")[1]
    panel = {"X-Requested-With": "panel"}
    assert (await a.get("/panel/api/auth/invite", params={"token": token})).json()["login_hint"] == "hr-owner"
    r = await a.post("/panel/api/auth/register", headers=panel, json={"login": "hr-owner", "password": "owner-password-42"})
    assert r.status_code == 201 and r.json()["project"] is None
    r = await a.post("/panel/api/auth/claim", headers=panel, json={"token": token})
    assert r.status_code == 200 and r.json()["role"] == "owner" and r.json()["project"]["id"] == pid

    # 2. The owner uploads documentation on the site; the RAG indexes it; the integration learns about it
    r = await a.post("/panel/api/documents", headers=panel, data={"section": "general"},
                     files={"files": ("vacation.md", DOC.encode(), "text/markdown")})
    assert r.status_code == 200, r.text
    await _wait_rag_jobs(f"p-{pid}")
    docs = (await a.get("/panel/api/documents")).json()
    assert [d["title"] for d in docs["published"]["documents"]] == ["Регламент отпусков"]
    async with admin_db.sessionmaker()() as s:
        assert await admin_docs.follow_jobs(platform.core, s) == 1

    # 3. The owner gives a colleague the «user» status by email (the mail sends its own user id to the platform)
    r = await m.put(f"/platform/projects/{pid}/members", headers=owner, json={"email": "colleague@corp.example.com", "role": "user"})
    assert r.status_code == 200, r.text

    # 4. The colleague asks in the chat: a grounded answer with a source and a signed link to the document
    r = await m.post("/chat/ask", headers=colleague, json={"message": "Где оформляется заявление на отпуск?"})
    assert r.status_code == 200, r.text
    ans = r.json()
    assert ans["action"] == "answer", (ans, CALLS[-1:] if CALLS else None)
    assert "кадровом портале" in ans["text"] and ans["sources"][0]["document_title"] == "Регламент отпусков"
    link = ans["sources"][0]["url"]
    assert link.startswith("https://platform.test/v1/public/rag/documents/")
    page = await a.get(link.replace("https://platform.test", ""))
    assert page.status_code == 200 and "Регламент отпусков" in page.text
    forged = await a.get(re.sub(r"sig=[^&#]+", "sig=forged", link).replace("https://platform.test", ""))
    assert forged.status_code == 404

    # 5. «Спросить у ИИ» on a draft: the answer is in the documentation, the letter need not be sent
    r = await m.post("/mail/ask", headers=colleague, json={"draft": "Коллеги, кто согласует отпуск?"})
    assert r.status_code == 200 and r.json()["recommendation"] == "answer_found", r.text

    # 5b. «Ответить с ИИ» on an incoming letter: a draft from the documentation, unknowns left to the user
    r = await m.post("/mail/reply-draft", headers=colleague, json={
        "letter": "Добрый день! Где оформляется заявление на отпуск? И сколько стоит парковка у офиса?",
        "subject": "Вопросы", "author": "Иван <ivan@corp.example.com>"})
    assert r.status_code == 200, r.text
    reply = r.json()
    assert "кадровом портале" in reply["draft"] and "[1]" not in reply["draft"], reply
    assert reply["todo"] == ["И сколько стоит парковка у офиса?"] and "[уточнить:" in reply["draft"]

    # 6. A question the documentation does not cover goes to the owner and admins
    r = await m.post("/chat/ask", headers=colleague, json={"message": "Сколько стоит парковка у офиса?"})
    assert r.json()["action"] == "offer_operator" and r.json()["question_id"]
    # (the letter's question from step 5b is there too: a gap in the documentation either way)
    pending = (await a.get("/panel/api/questions")).json()["questions"]
    assert [q["text"].split("\n")[0] for q in pending] == ["Сколько стоит парковка у офиса?", "И сколько стоит парковка у офиса?"]
    r = await a.post(f"/panel/api/questions/{pending[0]['id']}/answer", headers=panel,
                     json={"text": "Парковка для сотрудников бесплатная, пропуск выдаёт охрана.", "save_to_kb": True})
    assert r.status_code == 200 and r.json()["saved_to_kb"] is True

    # 7. The admin's answer reaches the colleague in the mail as a notification (events polled by the mail)
    async with mail_db._sessionmaker() as s:
        assert await mail_notifications.poll_once(platform.platform_client, s) >= 1
    notes = (await m.get("/notifications", headers=colleague)).json()["notifications"]
    assert any("бесплатная" in n["text"] for n in notes)

    # 8. The saved answer is now part of the documentation: next time the bot answers by itself
    await _wait_rag_jobs(f"p-{pid}")
    r = await m.post("/chat/ask", headers=colleague, json={"message": "Нужен ли пропуск на парковку?"})
    assert r.json()["action"] == "answer", r.json()

    # 9. The colleague asks for a human: a support ticket; support replies on the site; the reply reaches the mail
    r = await m.post("/chat/ask", headers=colleague, json={"message": "Позовите оператора"})
    key = r.json()["escalation"]["key"]
    r = await a.post(f"/panel/api/escalations/{key}/reply", headers=panel, json={"text": "Здравствуйте! Чем помочь?"})
    assert r.status_code == 201
    async with mail_db._sessionmaker() as s:
        await mail_notifications.poll_once(platform.platform_client, s)
    notes = (await m.get("/notifications", headers=colleague)).json()["notifications"]
    assert any(n["text"] == "Здравствуйте! Чем помочь?" for n in notes)

    # 10. Statuses are enforced by the platform: a user cannot manage members, nobody outside the project can ask
    r = await m.put(f"/platform/projects/{pid}/members", headers=colleague, json={"email": "owner@corp.example.com", "role": "user"})
    assert r.status_code == 403
    stranger = await _register(m, "stranger@corp.example.com")
    r = await m.post("/chat/ask", headers=stranger, json={"message": "Где оформляется отпуск?"})
    assert r.status_code == 409 and r.json()["code"] == "no_project"

    # 11. Statistics on the site see all of it
    stats = (await a.get("/panel/api/stats")).json()
    assert stats["questions"] >= 5 and stats["escalations"]["open"] == 1 and stats["unique_users"] == 1

    # 12. A project created on the site: its owner registers there; a mail user joins it as an admin with the code
    #     and gives a colleague access from the mail
    async with httpx.AsyncClient(transport=a._transport, base_url=str(a.base_url)) as site:
        r = await site.post("/panel/api/auth/register", headers=panel, json={"login": "site-owner", "password": "site-password-42"})
        assert r.status_code == 201, r.text
        r = await site.post("/panel/api/projects", headers=panel, json={"name": "Бухгалтерия"})
        assert r.status_code == 201 and r.json()["role"] == "owner", r.text
        site_pid, site_code = r.json()["project"]["id"], r.json()["project_code"]
    r = await m.post("/platform/projects/join", headers=stranger, json={"project_code": site_code})
    assert r.status_code == 200 and r.json()["project"] == {**r.json()["project"], "id": site_pid, "role": "admin"}, r.text
    r = await m.put(f"/platform/projects/{site_pid}/members", headers=stranger, json={"email": "colleague@corp.example.com", "role": "user"})
    assert r.status_code == 200, r.text

    # 13. Every event went to the integration's feed in order
    async with admin_db.sessionmaker()() as s:
        feed = await admin_events.poll(s, 1, 0, 100)
    types = [e["type"] for e in feed]
    assert types[0] == "docs.updated" and "question.answered" in types and "escalation.created" in types
