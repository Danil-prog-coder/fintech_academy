"""The mail demo as an integration of the platform: projects, statuses, questions, notifications."""

from mail_api.db import session as db_session
from mail_api.db.models import Notification
from mail_api.services import notifications
from tests.conftest import PLATFORM_KEY, assert_error


async def test_create_project_and_ask_from_a_draft(world):
    h = await world.user()
    assert_error(await world.client.post("/mail/ask", headers=h, json={"draft": "Где регламент?"}), 409, "no_project")
    r = await world.client.post("/platform/projects", headers=h, json={"name": "Отдел продаж", "login": "dev"})
    assert r.status_code == 201
    created = r.json()
    assert created["project_code"] and created["owner_panel_setup_url"]
    # the demo sends our own id as external_id, never the email
    create_call = next(c for c in world.platform.calls if c[0] == "POST" and c[1] == "/v1/projects")
    assert create_call[2]["owner_external_id"] == "mail-user-1" and create_call[4] == PLATFORM_KEY
    projects = (await world.client.get("/platform/projects", headers=h)).json()
    assert projects["current_project_id"] == created["project"]["id"] and projects["projects"][0]["role"] == "owner"
    r = await world.client.post("/mail/ask", headers=h, json={"draft": "Привет! Где регламент? И кто согласует отпуск?",
                                                               "subject": "Вопросы", "thread": [{"text": "раньше обсуждали"}]})
    body = r.json()
    assert r.status_code == 200 and [x["question"] for x in body["results"]] == ["Где регламент?", "И кто согласует отпуск?"]
    assert body["recommendation"] == "answer_found" and body["results"][0]["sources"][0]["document_title"] == "Регламент"
    asked = [c[2] for c in world.platform.calls if c[1].endswith("/ask")]
    assert asked[0]["channel"] == "mail" and "тема письма: Вопросы" in asked[0]["message"]
    world.platform.action = "offer_operator"
    r = await world.client.post("/mail/ask", headers=h, json={"draft": "Сколько стоит парковка?"})
    assert r.json()["recommendation"] == "no_answer"


async def test_owner_gives_statuses_by_email_of_our_users(world):
    owner = await world.user("owner@example.com")
    colleague = await world.user("colleague@example.com")
    pid = (await world.client.post("/platform/projects", headers=owner, json={"name": "П", "login": "owner"})).json()["project"]["id"]
    # the colleague is not in the project yet
    assert_error(await world.client.post("/chat/ask", headers=colleague, json={"message": "Привет"}), 409, "no_project")
    assert_error(await world.client.put(f"/platform/projects/{pid}/members", headers=owner,
                                        json={"email": "nobody@example.com", "role": "user"}), 404, "user_not_registered")
    r = await world.client.put(f"/platform/projects/{pid}/members", headers=owner,
                               json={"email": "colleague@example.com", "role": "support", "login": "sup"})
    assert r.status_code == 200 and r.json()["panel_setup_url"]
    members = (await world.client.get(f"/platform/projects/{pid}/members", headers=owner)).json()["members"]
    assert {m["email"]: m["role"] for m in members} == {"owner@example.com": "owner", "colleague@example.com": "support"}
    # the platform's rules come back as they are: a non-owner cannot assign statuses
    assert_error(await world.client.put(f"/platform/projects/{pid}/members", headers=colleague,
                                        json={"email": "owner@example.com", "role": "user"}), 403, "owner_only")
    r = await world.client.post("/chat/ask", headers=colleague, json={"message": "Как оформить отпуск?"})
    assert r.status_code == 200 and r.json()["text"] == "Ответ на: Как оформить отпуск?"
    assert (await world.client.delete(f"/platform/projects/{pid}/members/colleague@example.com", headers=owner)).status_code == 204
    projects = (await world.client.get("/platform/projects", headers=colleague)).json()
    assert projects == {"projects": [], "current_project_id": None}


async def test_events_become_notifications_of_the_right_user(world):
    h = await world.user()
    await world.user("other@example.com")
    world.platform.events = [
        {"id": 1, "event_id": "e1", "type": "question.answered", "project_id": "00000001",
         "data": {"external_id": "mail-user-1", "question": "Где парковка?", "answer": "Во дворе"}},
        {"id": 2, "event_id": "e2", "type": "escalation.message", "project_id": "00000001",
         "data": {"external_id": "mail-user-2", "key": "ESC-1", "text": "Смотрю"}},
        {"id": 3, "event_id": "e3", "type": "escalation.message", "project_id": "00000001",
         "data": {"external_id": "telegram-77", "key": "ESC-2", "text": "чужой пользователь"}},
        {"id": 4, "event_id": "e4", "type": "docs.updated", "project_id": "00000001", "data": {}},
    ]
    async with db_session._sessionmaker() as s:
        assert await notifications.poll_once(world.app.state.platform, s) == 2
    async with db_session._sessionmaker() as s:  # the cursor is saved: nothing is delivered twice
        assert await notifications.poll_once(world.app.state.platform, s) == 0
    assert len(await world.rows(Notification)) == 2
    mine = (await world.client.get("/notifications", headers=h)).json()["notifications"]
    assert [n["text"] for n in mine] == ["Во дворе"] and not mine[0]["read"]
    assert (await world.client.post("/notifications/read", headers=h, json={})).status_code == 204
    assert (await world.client.get("/notifications", headers=h, params={"unread": True})).json()["notifications"] == []


async def test_platform_outage_is_a_clear_retryable_error(world):
    h = await world.user()
    await world.client.post("/platform/projects", headers=h, json={"name": "П", "login": "dev"})
    world.platform.down = True
    assert_error(await world.client.post("/chat/ask", headers=h, json={"message": "Привет"}), 503, "platform_unavailable", True)
