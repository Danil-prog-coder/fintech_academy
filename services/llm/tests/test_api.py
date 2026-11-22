"""HTTP contract (FR-AGT-10): SSE events, tokens, feedback, journal, jobs, operators' answers. Agent is faked."""

import json
import time

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

import rag_service.api.app as app_mod
from rag_service import db, jobs
from rag_service.analytics.query_logger import QueryLogger
from rag_service.config import get_settings


def fake_events(session_id, project_id, message, images=None, now=None, debug=False, allowed_sections=None):
    yield {"type": "status", "text": "Ищу в документации…"}
    yield {"type": "delta", "text": "Ответ [1]"}
    yield {"type": "final", "action": "answer", "text": "Ответ [1]", "sources": [], "image_ids": [], "confidence": 0.9,
           "confidence_level": "high", "buttons": [], "session_id": session_id, "project_id": project_id or "default"}


@pytest.fixture
def client():
    return TestClient(app_mod.app)


def _log(request_id, text="Вопрос", action="answer", project="api-test", **extra):
    res = {"action": action, "text": "Ответ", "sources": [{"citation_label": "[1]", "document_title": "Док", "section_path": "Док → 1 Раздел → 1.1"}],
           "confidence": 0.8, "confidence_level": "high", "latency_ms": 1200, "first_token_ms": 400, "standalone": True,
           "usage": {"prompt_tokens": 100, "completion_tokens": 20, "llm_calls": 2, "cost_usd": 0.001, "cost_status": "known", "by_model": {"m": {}}},
           "trace": [{"step": "llm", "ms": 5}], **extra}
    QueryLogger().log_turn(project, "sess-1", request_id, text, res)


def test_ask_sse(monkeypatch, client):
    monkeypatch.setattr(app_mod, "ask_events", fake_events)
    with client.stream("POST", "/ask", json={"session_id": "u1", "message": "hi"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [l.split(": ", 1)[1] for l in body.splitlines() if l.startswith("event: ")]
    assert events == ["status", "delta", "final"]
    final = json.loads([l for l in body.splitlines() if l.startswith("data: ")][-1][6:])
    assert final["action"] == "answer" and final["session_id"] == "u1"


def test_ask_validation(client):
    assert client.post("/ask", json={"message": "no session"}).status_code == 422


def test_documents_and_upload_validation(monkeypatch, client):
    monkeypatch.setattr(app_mod.store, "active_manifest", lambda pid: {"generation": "g1", "documents": [
        {"doc_id": "bp", "title": "БП Командировка", "chunks": 3, "outline": ["1 Содержание"]}]})
    d = client.get("/documents").json()
    assert d["generation"] == "g1" and d["documents"][0]["title"] == "БП Командировка"
    assert client.get("/documents/bp/outline").json()["outline"] == ["1 Содержание"]
    r = client.post("/documents", files={"files": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415


def test_upload_stages_by_default_and_explicit_reindex_publishes(monkeypatch, client, tmp_path):
    monkeypatch.setattr(get_settings(), "kb_dir", str(tmp_path))
    calls = []

    def start(*args):
        calls.append(args)
        return {"job_id": "publish-1", "status": "queued"}

    monkeypatch.setattr(app_mod, "_start_job", start)
    for data in ({}, {"index": "false"}):
        response = client.post("/documents", data=data,
                               files={"files": ("guide.txt", b"instructions", "text/plain")})
        assert response.status_code == 200
        assert response.json()["status"] == "staged"
        assert response.json()["job"] is None
    assert not calls
    assert (tmp_path / "general" / "guide.txt").read_bytes() == b"instructions"
    assert client.post("/reindex", json={"project_id": "default"}).json()["job_id"] == "publish-1"
    assert len(calls) == 1


def test_confluence_import_does_not_trigger_publication(monkeypatch, client):
    calls = []
    def receive(source_id, body, start):
        assert start is None
        calls.append((source_id, body))
        return {"accepted": True, "batch_id": "b1", "job_id": None,
                "message": "staged; awaiting explicit publication"}
    monkeypatch.setattr(app_mod.confluence_source, "receive_batch", receive)
    result = client.post("/sources/team-docs/batches", json={"batch_id": "b1"})
    assert result.status_code == 200 and result.json()["job_id"] is None
    assert calls == [("team-docs", {"batch_id": "b1"})]


def test_manual_import_is_scoped_and_recorded_without_publishing(monkeypatch, client):
    monkeypatch.setattr(app_mod.confluence_source, "allowed_sources", lambda: {"team": {"project_id": "p1"}})
    calls = []
    monkeypatch.setattr(app_mod.confluence_control, "import_source", lambda *args: calls.append(args) or {
        "status": "ok", "import_status": "staged", "published": False})
    def start(kind, project, fn, **kwargs):
        assert kind == "confluence-import" and project == "p1"
        assert fn()["published"] is False
        return {"job_id": "import-1", "status": "queued"}
    monkeypatch.setattr(jobs, "start_fn", start)
    url = "/confluence/sources/team/sync"
    assert client.post(url, json={"project_id": "other"}).status_code == 404
    assert calls == []
    result = client.post(url, json={"project_id": "p1", "page_url": "https://site/wiki/pages/1"})
    assert result.json()["job_id"] == "import-1"
    assert calls == [("p1", "team", "https://site/wiki/pages/1")]


def test_registration_cannot_use_a_template_from_another_project(monkeypatch, client):
    monkeypatch.setattr(app_mod.confluence_source, "allowed_sources", lambda: {"team": {"project_id": "p1"}})
    calls = []
    monkeypatch.setattr(app_mod.confluence_control, "register_source", lambda *args: calls.append(args) or {"managed": True})
    body = {"project_id": "other", "template_source_id": "team", "page_url": "https://site/wiki/pages/1"}
    assert client.post("/confluence/sources", json=body).status_code == 404
    assert calls == []
    assert client.post("/confluence/sources", json=dict(body, project_id="p1")).status_code == 200
    assert len(calls) == 1


def test_tokens_are_required_everywhere_except_health(monkeypatch, client):
    s = get_settings()
    monkeypatch.setattr(app_mod, "ask_events", fake_events)
    monkeypatch.setattr(s, "auth_disabled", False)
    monkeypatch.setattr(s, "service_api_token", "")
    monkeypatch.setattr(s, "admin_api_token", "")
    ask = {"session_id": "u1", "message": "hi"}
    # nothing configured: closed, not open
    for method, path in (("post", "/ask/sync"), ("get", "/documents"), ("get", "/analytics/summary"), ("get", "/faq/stats"),
                         ("get", "/faq/popular"), ("get", "/git/sources"), ("get", "/jobs")):
        r = client.post(path, json=ask) if method == "post" else client.get(path)
        assert r.status_code == 503, path
    assert client.get("/health").status_code == 200 and client.get("/health").json()["auth"] == "missing"
    monkeypatch.setattr(s, "service_api_token", "svc")
    monkeypatch.setattr(s, "admin_api_token", "adm")
    svc, adm = {"Authorization": "Bearer svc"}, {"Authorization": "Bearer adm"}
    assert client.post("/ask/sync", json=ask).status_code == 401
    assert client.post("/ask/sync", json=ask, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/ask/sync", json=ask, headers=svc).status_code == 200
    assert client.post("/ask/sync", json=ask, headers=adm).status_code == 200
    # the bot's token does not open the panel part
    for path in ("/analytics/summary", "/analytics/requests", "/faq/entries", "/git/sources", "/jobs", "/analytics/taxonomy"):
        assert client.get(path, headers=svc).status_code == 401, path
    assert client.get("/analytics/summary", headers=adm).status_code == 200
    assert client.get("/jobs", headers=adm).status_code == 200
    # webhooks are verified by their own signature, not by a bearer token
    assert client.post("/webhooks/github", content=b"not json").status_code == 400


def test_feedback_journal_and_summary(client):
    _log("req-up", "Как настроить фильтр?")
    _log("req-down", "Где кнопка печати?")
    _log("req-esc", "Позовите оператора", action="escalate")
    assert client.post("/feedback", json={"request_id": "nope", "rating": "up"}).status_code == 404
    assert client.post("/feedback", json={"request_id": "req-up"}).status_code == 422
    assert client.post("/feedback", json={"request_id": "req-up", "rating": "up"}).json() == {"ok": True}
    down = client.post("/feedback", json={"request_id": "req-down", "rating": "down", "comment": "не то"}).json()
    assert down["offer_operator"] is True  # FR-BOT-04: 👎 offers an escalation
    assert client.post("/feedback", json={"request_id": "req-esc", "escalation_unneeded": True}).status_code == 200

    rows = client.get("/analytics/requests", params={"project_id": "api-test"}).json()
    assert {r["request_id"]: r["feedback"] for r in rows} == {"req-up": "up", "req-down": "down", "req-esc": None}
    assert [r["request_id"] for r in client.get("/analytics/requests", params={"project_id": "api-test", "action": "escalate"}).json()] == ["req-esc"]
    one = client.get("/analytics/requests/req-down").json()
    assert one["turn"]["trace"] == [{"step": "llm", "ms": 5}] and one["feedback"] == "down"
    assert one["feedback_history"][0]["comment"] == "не то"
    assert one["turn"]["session"] != "sess-1"  # pseudonymised
    assert client.get("/analytics/requests/unknown").status_code == 404

    m = client.get("/analytics/summary", params={"project_id": "api-test"}).json()
    assert m["requests"] == 3 and m["feedback"] == {"up": 1, "down": 1}
    assert m["success_rate"] == round(1 / 3, 3) and m["escalation_rate"] == round(1 / 3, 3)
    assert m["escalations_marked_unneeded"] == 1 and m["first_token_ms"]["avg"] == 400
    assert m["cost_usd_est"] == 0.003
    assert any("Док → 1 Раздел" in name for name, _ in m["top_doc_sections"])


def test_turns_and_classification_live_in_the_database(monkeypatch, client):
    from types import SimpleNamespace

    import rag_service.analytics.classify as cls

    _log("req-cls", "Почему не работает фильтр?", project="cls-test")

    def chat(**kw):
        n = kw["messages"][1]["content"].count("\n") + 1
        items = [{"i": i, "topic": "БАРС-Офис: фильтры", "type": "почему не работает", "object": "фильтр", "new_topic": None} for i in range(n)]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"items": items}, ensure_ascii=False)))])

    monkeypatch.setattr(cls, "chat", chat)
    r = client.post("/analytics/classify", json={"days": 30, "limit": 500}).json()
    assert r["classified"] >= 1 and r["by_llm"] >= 1
    row = next(x for x in client.get("/analytics/requests", params={"project_id": "cls-test"}).json() if x["request_id"] == "req-cls")
    assert row["topic"] == "БАРС-Офис: фильтры" and row["type"] == "почему не работает"
    # stored in tables, not in files of the state directory
    assert db.one(sa.select(db.classes).where(db.classes.c.request_id == "req-cls"))["data"]["topic"] == "БАРС-Офис: фильтры"
    assert db.one(sa.select(db.turns.c.record).where(db.turns.c.request_id == "req-cls"))["record"]["text"] == "Почему не работает фильтр?"
    tx = client.put("/analytics/taxonomy", json={"topics": ["Тема А", "Вне тематики"]}).json()
    assert tx["topics"] == ["Тема А", "Вне тематики"] and client.get("/analytics/taxonomy").json()["topics"] == tx["topics"]
    cls.get_classifier().save_taxonomy({"topics": list(cls.DEFAULT_TOPICS)})


def test_jobs_survive_restart_and_bootstrap(monkeypatch, tmp_path):
    s = get_settings()
    calls = []

    def fake_ingest(paths, project_id, describe=True):
        calls.append((list(paths), project_id))
        return {"status": "ok", "counts": {"chunks": 1}}

    monkeypatch.setattr(jobs, "ingest", fake_ingest)
    monkeypatch.setattr(jobs, "invalidate", lambda pid: None)
    monkeypatch.setattr(s, "faq_enabled", False)
    done = jobs.start("reindex", ["kb"], "default", wait=True)
    assert done["status"] == "done" and done["report"]["counts"] == {"chunks": 1}
    assert jobs.get(done["job_id"])["status"] == "done"  # read back from the database, not from process memory

    # an indexing job that was running when the process died is repeated; a Git sync (a closure) is only marked
    db.execute(sa.insert(db.jobs).values(job_id="dead1", kind="upload:append", status="running", project_id="default",
                                         params={"paths": ["kb2"], "describe": False}, created_at=time.time()))
    db.execute(sa.insert(db.jobs).values(job_id="dead2", kind="git_sync:webhook", status="queued", project_id="default",
                                         params=None, created_at=time.time() + 1))
    monkeypatch.setattr(jobs.store, "active_generation", lambda pid: "g1")
    started = jobs.on_startup()
    assert jobs.get("dead1")["status"] == "interrupted" and jobs.get("dead2")["status"] == "interrupted"
    assert len(started) == 1 and started[0]["kind"] == "resume:upload:append"
    for _ in range(50):
        if jobs.get(started[0]["job_id"])["status"] == "done":
            break
        time.sleep(0.05)
    assert calls[-1] == (["kb2"], "default")

    # FR-ADM-02: nothing published yet → the bundled folder is indexed on start-up
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "doc.md").write_text("# Док\n\nТекст", encoding="utf-8")
    monkeypatch.setattr(s, "kb_dir", str(kb))
    monkeypatch.setattr(s, "auto_index_on_start", True)
    monkeypatch.setattr(jobs.store, "active_generation", lambda pid: None)
    boot = jobs.on_startup()
    assert [j["kind"] for j in boot] == ["bootstrap"]
    for _ in range(50):
        if jobs.get(boot[0]["job_id"])["status"] == "done":
            break
        time.sleep(0.05)
    assert calls[-1] == ([str(kb)], "default")
    monkeypatch.setattr(jobs.store, "active_generation", lambda pid: "g1")
    assert jobs.on_startup() == []  # a published base is left alone


def test_closure_jobs_are_recorded(monkeypatch):
    monkeypatch.setattr(jobs, "invalidate", lambda pid: None)
    ok = jobs.start_fn("faq_recompute", "default", lambda: {"status": "ok", "clusters": 2}, wait=True, exclusive=False)
    assert ok["status"] == "done" and ok["report"] == {"status": "ok", "clusters": 2} and ok["params"] is None

    def boom():
        raise RuntimeError("repo is gone")

    bad = jobs.start_fn("git_sync:full", "default", boom, wait=True)
    assert bad["status"] == "failed" and "repo is gone" in bad["error"]
    assert {j["job_id"] for j in jobs.recent(50)} >= {ok["job_id"], bad["job_id"]}


def test_knowledge_from_operator_answer(monkeypatch, tmp_path, client):
    import rag_service.knowledge as kn
    from rag_service.ingest.md_parser import parse_markdown

    s = get_settings()
    monkeypatch.setattr(s, "kb_dir", str(tmp_path))
    monkeypatch.setattr(kn.jobs, "start", lambda kind, paths, pid, wait=False: {"job_id": "j1", "kind": kind, "status": "queued"})
    r = client.post("/knowledge", json={"question": "Как сбросить пароль в личном кабинете?",
                                        "answer": "Нажмите «Забыли пароль» на странице входа.\n# не заголовок", "author": "Мария"})
    assert r.status_code == 200 and r.json()["job"]["kind"] == "knowledge"
    doc = parse_markdown(tmp_path / r.json()["file"])
    assert doc.title.startswith("Ответ поддержки, ") and doc.source_type == "support"
    assert [b.text for b in doc.blocks if b.kind == "heading"] == ["Как сбросить пароль в личном кабинете?"]
    assert any("Забыли пароль" in b.text for b in doc.blocks)
    assert client.post("/knowledge", json={"question": "x", "answer": "y"}).status_code == 422
