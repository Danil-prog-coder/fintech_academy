from sqlalchemy import select

from app.db import session as db_session
from app.db.models import Message, QuestionLog
from app.services.mail import extract_questions
from tests.conftest import register, set_repo_status

URL = "https://github.com/acme/project"


def test_extract_questions():
    qs = extract_questions("Привет! Где описан релиз? И как настроен деплой?\nСпасибо.")
    assert qs == ["Где описан релиз?", "И как настроен деплой?"]
    assert extract_questions("Расскажи про деплой") == ["Расскажи про деплой"]


async def test_mail_ask_no_answer_and_privacy(client):
    h = await register(client)
    await client.post("/repo/connect", json={"url": URL}, headers=h)
    await set_repo_status("ready", "abc123")

    r = await client.post(
        "/mail/ask",
        json={
            "draft": "Коллега, где описан процесс релиза?",
            "subject": "Релиз",
            "recipients": ["boss@example.com"],
            "thread": [{"author": "boss@example.com", "text": "секретный контекст"}],
        },
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["recommendation"] == "no_answer"
    assert body["results"][0]["status"] == "not_found"

    # тексты письма и переписки не сохраняются; в журнале только хэш
    async with db_session._sessionmaker() as s:
        assert (await s.scalars(select(Message))).all() == []
        log = await s.scalar(select(QuestionLog))
        assert log.source == "mail" and len(log.question_hash) == 64

    fb = await client.post(
        "/feedback",
        json={"question_log_id": body["results"][0]["question_log_id"], "helpful": False},
        headers=h,
    )
    assert fb.status_code == 201


async def test_mail_ask_requires_repo_and_valid_input(client):
    h = await register(client)
    r = await client.post("/mail/ask", json={"draft": "Вопрос?"}, headers=h)
    assert r.status_code == 409
    bad = await client.post("/mail/ask", json={"draft": "x", "recipients": ["nope"]}, headers=h)
    assert bad.status_code == 422
