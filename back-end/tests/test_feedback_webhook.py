import hashlib
import hmac
import json

from sqlalchemy import select

from app.db import session as db_session
from app.db.models import Feedback, Job
from tests.conftest import register, set_repo_status

URL = "https://github.com/acme/project"


async def _ready_user(client, email="user@example.com"):
    h = await register(client, email)
    await client.post("/repo/connect", json={"url": URL}, headers=h)
    await set_repo_status("ready", "abc123")
    return h


async def test_feedback_on_chat_message(client):
    h = await _ready_user(client)
    ans = (await client.post("/qa/ask", json={"question": "Вопрос?"}, headers=h)).json()
    r = await client.post(
        "/feedback", json={"message_id": ans["message_id"], "helpful": True, "comment": "ок"}, headers=h
    )
    assert r.status_code == 201
    async with db_session._sessionmaker() as s:
        fb = await s.scalar(select(Feedback))
        assert fb.helpful is True and fb.message_id == ans["message_id"]


async def test_feedback_validation_and_isolation(client):
    h = await _ready_user(client)
    both = await client.post(
        "/feedback", json={"message_id": 1, "question_log_id": 1, "helpful": True}, headers=h
    )
    assert both.status_code == 422
    none = await client.post("/feedback", json={"helpful": True}, headers=h)
    assert none.status_code == 422

    ans = (await client.post("/qa/ask", json={"question": "Вопрос?"}, headers=h)).json()
    h2 = await register(client, "other@example.com")
    r = await client.post(
        "/feedback", json={"message_id": ans["message_id"], "helpful": True}, headers=h2
    )
    assert r.status_code == 404


def _signed(payload: dict, secret="hook-secret"):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


def _push(after):
    return {"repository": {"full_name": "acme/project"}, "after": after}


async def _post(client, body, sig, event="push"):
    return await client.post(
        "/github/webhook",
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/json",
        },
    )


async def test_webhook_rejects_bad_signature(client):
    await _ready_user(client)
    body, _ = _signed(_push("c1"))
    assert (await _post(client, body, "sha256=deadbeef")).status_code == 401
    assert (await _post(client, body, "")).status_code == 401
    wrong_secret = _signed(_push("c1"), secret="other")
    assert (await _post(client, *wrong_secret)).status_code == 401


async def test_webhook_push_is_idempotent_and_sets_updating(client):
    h = await _ready_user(client)
    body, sig = _signed(_push("c1"))
    assert (await _post(client, body, sig)).json() == {"accepted": True, "detail": None}
    again = await _post(client, body, sig)
    assert again.json()["detail"] == "уже в очереди"

    async with db_session._sessionmaker() as s:
        jobs = (await s.scalars(select(Job).where(Job.type == "index_update"))).all()
        assert len(jobs) == 1
    assert (await client.get("/repo/status", headers=h)).json()["status"] == "updating"


async def test_webhook_ping_unknown_repo_and_other_events(client):
    body, sig = _signed({"zen": "x"})
    assert (await _post(client, body, sig, event="ping")).json()["detail"] == "pong"
    body, sig = _signed(_push("c1"))
    assert (await _post(client, body, sig)).json()["accepted"] is False
    assert (await _post(client, body, sig, event="issues")).json()["accepted"] is False
