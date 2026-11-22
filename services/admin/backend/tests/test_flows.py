import json

from admin_api import db
from admin_api.security import verify_webhook
from admin_api.services import docs, escalations, events
from tests.conftest import create_project, panel_login, set_password


async def _project_with_user(env):
    data = await create_project(env)
    pid = data["project"]["id"]
    await env.client.put(f"/v1/projects/{pid}/members/u-1", headers=env.h, json={"acting_external_id": "u-owner", "role": "user"})
    pw = await set_password(env, data["owner_panel_setup_url"])
    h = await panel_login(env, "owner", pw)
    return pid, h, data


async def _events(env, after=0):
    return (await env.client.get("/v1/events", headers=env.h, params={"after": after})).json()["events"]


async def test_ask_requires_membership_and_hides_internal_fields(env):
    pid, _, _ = await _project_with_user(env)
    r = await env.client.post(f"/v1/projects/{pid}/ask", headers=env.h, json={"external_id": "stranger", "message": "Привет"})
    assert r.status_code == 403 and r.json()["code"] == "not_a_member"
    r = await env.client.post(f"/v1/projects/{pid}/ask", headers=env.h,
                              json={"external_id": "u-1", "message": "Как оформить отпуск?", "channel": "mail"})
    body = r.json()
    assert r.status_code == 200 and body["action"] == "answer" and body["request_id"] == "req0001"
    assert "usage" not in body and "trace" not in body and "chunk_id" not in body["sources"][0]
    assert body["images"] == [{"id": "d/img001.png", "url": f"https://api.test/v1/projects/{pid}/images/d/img001.png"}]
    sent = [c for c in env.rag.calls if c[1] == "/ask/sync"][0]
    payload, headers = sent[2], sent[4]
    assert payload["project_id"] == f"p-{pid}" and "u-1" not in payload["session_id"]
    assert headers["authorization"] == "Bearer tok"
    img = await env.client.get(f"/v1/projects/{pid}/images/d/img001.png", headers=env.h)
    assert img.status_code == 200 and img.content == b"PNG"


async def test_ask_stream_passes_progress_and_one_final(env):
    pid, _, _ = await _project_with_user(env)
    async with env.client.stream("POST", f"/v1/projects/{pid}/ask", headers=env.h,
                                 json={"external_id": "u-1", "message": "Вопрос", "stream": True}) as r:
        text = "".join([chunk async for chunk in r.aiter_text()])
    assert r.headers["content-type"].startswith("text/event-stream")
    kinds = [line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("event: ")]
    assert kinds == ["status", "delta", "final"]
    final = json.loads([line for line in text.splitlines() if line.startswith("data: ")][-1][6:])
    assert final["action"] == "answer" and "usage" not in final


async def test_no_answer_goes_to_admins_and_their_answer_reaches_the_user(env):
    pid, h, _ = await _project_with_user(env)
    env.rag.answer = {"action": "offer_operator", "reason": "no_evidence", "text": "Я пока не нашёл точного ответа.",
                      "buttons": [{"text": "Связаться с поддержкой", "action": "escalate"}]}
    r = (await env.client.post(f"/v1/projects/{pid}/ask", headers=env.h, json={"external_id": "u-1", "message": "Где парковка?"})).json()
    assert r["action"] == "offer_operator" and r["question_id"]
    # a technical failure is not a documentation gap
    env.rag.answer = {"action": "offer_operator", "reason": "llm_unavailable", "text": "Сервис недоступен"}
    r2 = (await env.client.post(f"/v1/projects/{pid}/ask", headers=env.h, json={"external_id": "u-1", "message": "Где кофе?"})).json()
    assert "question_id" not in r2
    pending = (await env.client.get("/panel/api/questions")).json()
    assert pending["total"] == 1 and pending["questions"][0]["text"] == "Где парковка?"
    r = await env.client.post(f"/panel/api/questions/{r['question_id']}/answer", headers=h,
                              json={"text": "Парковка во дворе, пропуск у охраны.", "save_to_kb": True})
    assert r.status_code == 200 and r.json()["status"] == "answered" and r.json()["saved_to_kb"]
    knowledge = [c for c in env.rag.calls if c[1] == "/knowledge"][0][2]
    assert knowledge["project_id"] == f"p-{pid}" and knowledge["question"] == "Где парковка?"
    evs = await _events(env)
    answered = [e for e in evs if e["type"] == "question.answered"]
    assert answered and answered[0]["data"]["external_id"] == "u-1" and answered[0]["project_id"] == pid
    # the other integration never sees these events
    assert (await env.client.get("/v1/events", headers=env.hb)).json()["events"] == []


async def test_dislike_turns_into_a_question_once(env):
    pid, _, _ = await _project_with_user(env)
    r = (await env.client.post(f"/v1/projects/{pid}/ask", headers=env.h, json={"external_id": "u-1", "message": "Вопрос?"})).json()
    fb = lambda ext: env.client.post(f"/v1/projects/{pid}/feedback", headers=env.h,  # noqa: E731
                                     json={"external_id": ext, "request_id": r["request_id"], "value": -1})
    assert (await fb("u-owner")).status_code == 404  # somebody else's answer
    first = (await fb("u-1")).json()
    assert first["question_id"]
    assert "question_id" not in (await fb("u-1")).json()


async def test_escalation_flow_with_support_and_jira(env):
    pid, h, data = await _project_with_user(env)
    # Jira for the project (owner only)
    r = await env.client.put("/panel/api/jira", headers=h, json={"base_url": "https://acme.atlassian.net", "email": "a@b.c",
                                                                "api_token": "jira-token", "project_key": "SUP"})
    jira_cfg = r.json()
    assert jira_cfg["webhook_url"] == f"https://api.test/jira/webhook/{pid}" and jira_cfg["webhook_secret"]
    assert "api_token" not in (await env.client.get("/panel/api/jira")).json()
    # the agent escalates (the user asked for a human)
    env.rag.answer = {"action": "escalate", "reason": "user_request", "text": "Передаю дежурному", "summary": "Нужен человек",
                      "urgency": "high", "history": [{"role": "user", "text": "оператор"}]}
    r = (await env.client.post(f"/v1/projects/{pid}/ask", headers=env.h,
                               json={"external_id": "u-1", "message": "Позовите оператора"})).json()
    key = r["escalation"]["key"]
    # a second request does not open a second ticket
    r2 = await env.client.post(f"/v1/projects/{pid}/escalations", headers=env.h, json={"external_id": "u-1", "message": "ещё"})
    assert r2.json()["key"] == key
    # the Jira worker mirrors the ticket
    async with db.sessionmaker()() as s:
        await escalations.jira_pass(env.core, s)
    assert list(env.jira.issues) == ["SUP-1"] and "Позовите оператора" in env.jira.issues["SUP-1"]["description"]
    # support (a separate account) takes it and replies; an internal note never reaches the user
    r = await env.client.put(f"/v1/projects/{pid}/members/u-sup", headers=env.h,
                             json={"acting_external_id": "u-owner", "role": "support", "login": "sup1"})
    pw = await set_password(env, r.json()["panel_setup_url"])
    hs = await panel_login(env, "sup1", pw)
    assert (await env.client.post(f"/panel/api/escalations/{key}/take", headers=hs)).json()["status"] == "in_progress"
    await env.client.post(f"/panel/api/escalations/{key}/reply", headers=hs, json={"text": "Здравствуйте! Уже смотрю."})
    await env.client.post(f"/panel/api/escalations/{key}/reply", headers=hs, json={"text": "проверить права", "internal": True})
    # the user answers through the API
    assert (await env.client.post(f"/v1/projects/{pid}/escalations/{key}/messages", headers=env.h,
                                  json={"external_id": "u-1", "text": "Спасибо, жду"})).status_code == 201
    view = (await env.client.get(f"/v1/projects/{pid}/escalations/{key}", headers=env.h, params={"external_id": "u-1"})).json()
    assert [m["text"] for m in view["messages"]] == ["Позовите оператора", "Здравствуйте! Уже смотрю.", "Спасибо, жду"]
    assert (await env.client.get(f"/v1/projects/{pid}/escalations/{key}", headers=env.h,
                                 params={"external_id": "u-owner"})).status_code == 404
    async with db.sessionmaker()() as s:
        await escalations.jira_pass(env.core, s)
    texts = [t for _, t in env.jira.comments]
    assert texts == ["[Поддержка] Здравствуйте! Уже смотрю.", "// проверить права", "[Пользователь] Спасибо, жду"]
    assert ("SUP-1", "in_progress") in env.jira.transitions
    # Jira → platform: a comment from Jira reaches the user, a final status closes the ticket
    secret = jira_cfg["webhook_secret"]
    import hashlib
    import hmac

    def signed(payload):
        body = json.dumps(payload).encode()
        return body, {"X-Hub-Signature": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(),
                      "Content-Type": "application/json"}

    body, hdr = signed({"webhookEvent": "comment_created", "issue": {"key": "SUP-1"},
                        "comment": {"id": "777", "body": "Права выданы", "author": {"displayName": "Иван"}}})
    forged = {**hdr, "X-Hub-Signature": "sha256=bad"}
    assert (await env.client.post(f"/jira/webhook/{pid}", content=body, headers=forged)).status_code == 401
    assert (await env.client.post(f"/jira/webhook/{pid}", content=body, headers=hdr)).status_code == 204
    assert (await env.client.post(f"/jira/webhook/{pid}", content=body, headers=hdr)).status_code == 204  # duplicate: ignored
    body, hdr = signed({"webhookEvent": "jira:issue_updated", "issue": {"key": "SUP-1"},
                        "changelog": {"items": [{"field": "status", "toString": "Done"}]}})
    await env.client.post(f"/jira/webhook/{pid}", content=body, headers=hdr)
    evs = await _events(env)
    msgs = [e["data"]["text"] for e in evs if e["type"] == "escalation.message"]
    assert msgs == ["Здравствуйте! Уже смотрю.", "Права выданы"]
    statuses = [e["data"]["status"] for e in evs if e["type"] == "escalation.status_changed"]
    assert statuses[-1] == "resolved"
    # closed: the user rates it and cannot write any more
    assert (await env.client.post(f"/v1/projects/{pid}/escalations/{key}/rating", headers=env.h,
                                  json={"external_id": "u-1", "value": 1})).status_code == 200
    assert (await env.client.post(f"/v1/projects/{pid}/escalations/{key}/messages", headers=env.h,
                                  json={"external_id": "u-1", "text": "ещё"})).status_code == 409


async def test_jira_failures_are_retried_and_then_given_up(env):
    pid, h, _ = await _project_with_user(env)
    await env.client.put("/panel/api/jira", headers=h, json={"base_url": "https://acme.atlassian.net", "email": "a@b.c",
                                                            "api_token": "t", "project_key": "SUP"})
    env.jira.fail = True
    r = await env.client.post(f"/v1/projects/{pid}/escalations", headers=env.h, json={"external_id": "u-1", "message": "Помогите"})
    key = r.json()["key"]
    from datetime import timedelta

    from admin_api.models import Escalation
    for _ in range(env.settings.jira_max_attempts):
        async with db.sessionmaker()() as s:
            await escalations.jira_pass(env.core, s)
            e = await s.get(Escalation, escalations.key_to_id(key))
            e.jira_next_at = e.jira_next_at - timedelta(hours=1) if e.jira_next_at else None
            await s.commit()
    view = (await env.client.get(f"/panel/api/escalations/{key}")).json()
    assert view["jira_state"] == "failed" and view["jira_error"]
    # the ticket still works from the site
    assert (await env.client.post(f"/panel/api/escalations/{key}/reply", headers=h, json={"text": "Отвечаю тут"})).status_code == 201


async def test_webhooks_are_signed_retried_and_skipped_without_url(env):
    pid, h, _ = await _project_with_user(env)
    env.rag.answer = {"action": "offer_operator", "reason": "no_evidence", "text": "нет"}
    await env.client.post(f"/v1/projects/{pid}/ask", headers=env.h, json={"external_id": "u-1", "message": "Вопрос 1"})
    qid = (await env.client.get("/panel/api/questions")).json()["questions"][0]["id"]
    await env.client.post(f"/panel/api/questions/{qid}/answer", headers=h, json={"text": "Ответ админа"})
    async with db.sessionmaker()() as s:  # no webhook configured: skipped, but still pollable
        await events.deliver_pending(env.core, s)
    assert env.out.requests == [] and (await _events(env))
    r = await env.client.put("/v1/integration/webhook", headers=env.h, json={"url": "http://mail:8000/hooks/platform"})
    secret = r.json()["secret"]
    await env.client.post(f"/v1/projects/{pid}/ask", headers=env.h, json={"external_id": "u-1", "message": "Вопрос 2"})
    qid2 = (await env.client.get("/panel/api/questions")).json()["questions"][0]["id"]
    env.out.status = 500
    await env.client.post(f"/panel/api/questions/{qid2}/answer", headers=h, json={"text": "Второй ответ"})
    async with db.sessionmaker()() as s:
        assert await events.deliver_pending(env.core, s) == 0
    assert len(env.out.requests) == 1
    from admin_api.models import Event
    async with db.sessionmaker()() as s:  # make the retry due now
        ev = (await s.scalars(db.select(Event).where(Event.delivery_status == "pending"))).one()
        ev.next_attempt_at = ev.created_at
        await s.commit()
    env.out.status = 200
    async with db.sessionmaker()() as s:
        assert await events.deliver_pending(env.core, s) == 1
    req = env.out.requests[-1]
    assert req.headers["X-Platform-Event"] == "question.answered"
    assert verify_webhook(secret, req.content, req.headers["X-Platform-Signature"])
    assert json.loads(req.content)["data"]["answer"] == "Второй ответ"


async def test_webhook_url_must_be_public_https_in_production(env):
    env.core.settings.webhook_allow_private = False
    for url in ("http://example.com/x", "https://127.0.0.1/x", "https://user:pw@example.com/x", "ftp://example.com"):
        r = await env.client.put("/v1/integration/webhook", headers=env.h, json={"url": url})
        assert r.status_code == 400, url


async def test_documents_upload_replace_needs_code_and_finished_jobs_are_announced(env):
    pid, h, data = await _project_with_user(env)
    files = {"files": ("a.md", b"# A\n\ntext", "text/markdown")}
    r = await env.client.post("/panel/api/documents", headers=h, files=files, data={"section": "general", "mode": "replace"})
    assert r.status_code == 403 and r.json()["code"] == "project_code_required"
    r = await env.client.post("/panel/api/documents", headers=h, files=files,
                              data={"section": "general", "mode": "replace", "project_code": data["project_code"]})
    assert r.status_code == 200
    upload = [c for c in env.rag.calls if c[0] == "POST" and c[1] == "/documents"][0]
    assert f"p-{pid}".encode() in upload[5] and b"replace" in upload[5]  # the project's own folder, replace mode
    assert (await env.client.post("/panel/api/documents", headers=h, files=files, data={"section": "nope"})).status_code == 400
    bad = {"files": ("a.exe", b"MZ", "application/octet-stream")}
    assert (await env.client.post("/panel/api/documents", headers=h, files=bad, data={"section": "general"})).status_code == 415
    env.rag.jobs["job1"] = {"job_id": "job1", "status": "done", "report": {"status": "ok", "generation": "g2"}}
    async with db.sessionmaker()() as s:
        assert await docs.follow_jobs(env.core, s) == 1
    upd = [e for e in await _events(env) if e["type"] == "docs.updated"]
    assert upd and upd[0]["data"]["generation"] == "g2"


async def test_signed_document_links_are_proxied_without_the_service_token(env):
    r = await env.client.get("/v1/public/rag/documents/d/view", params={"project_id": "p-x", "sig": "good"})
    assert r.status_code == 200 and r.text == "<html>doc</html>"
    assert (await env.client.get("/v1/public/rag/documents/d/view", params={"project_id": "p-x", "sig": "bad"})).status_code == 404
    assert (await env.client.get("/v1/public/rag/documents/d/view", params={"project_id": "p-x"})).status_code == 404
    assert (await env.client.get("/v1/public/rag/documents/d/outline", params={"sig": "good"})).status_code == 404


async def test_stats(env):
    pid, h, _ = await _project_with_user(env)
    await env.client.post(f"/v1/projects/{pid}/ask", headers=env.h, json={"external_id": "u-1", "message": "Вопрос"})
    s = (await env.client.get("/panel/api/stats", params={"days": 7})).json()
    assert s["questions"] == 1 and s["answered"] == 1 and s["unique_users"] == 1 and s["members"] == {"owner": 1, "user": 1}
    assert s["rag"] == {"topics": {"x": 1}}
    assert len(s["by_day"]) == 7 and sum(d["total"] for d in s["by_day"]) == 1  # every day, quiet ones included
