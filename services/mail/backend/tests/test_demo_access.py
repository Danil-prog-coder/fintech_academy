"""Тестовый доступ: кнопка на странице входа пускает гостя в готовый демо-аккаунт."""

from mail_api.core.config import get_settings
from mail_api.db.models import MailAccount, User
from tests.conftest import assert_error, bearer

DEMO_PID = "0000d001"
DEMO_CODE = f"{DEMO_PID}-{'s' * 24}"


def enable_demo(monkeypatch, mail, **extra) -> None:
    env = {
        "DEMO_ENABLED": "true",
        "DEMO_MAILBOX_EMAIL": "dev@mail.example.com",
        "DEMO_MAILBOX_PASSWORD": mail.password,
        "DEMO_MAILBOX_IMAP_HOST": "127.0.0.1",
        "DEMO_MAILBOX_IMAP_PORT": str(mail.imap_port),
        "DEMO_MAILBOX_IMAP_SECURITY": "none",
        "DEMO_MAILBOX_SMTP_HOST": "127.0.0.1",
        "DEMO_MAILBOX_SMTP_PORT": str(mail.smtp_port),
        "DEMO_MAILBOX_SMTP_SECURITY": "none",
        "DEMO_PROJECT_CODE": DEMO_CODE,
        **extra,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


async def test_demo_is_off_by_default(world):
    info = await world.client.get("/auth/demo")
    assert info.json()["enabled"] is False
    assert_error(await world.client.post("/auth/demo"), 404, "demo_disabled")


async def test_demo_login_gives_ready_mailbox_and_project(world, mail, monkeypatch):
    world.platform.projects[DEMO_PID] = {"name": "Демо", "members": {}}
    enable_demo(monkeypatch, mail)
    c = world.client

    info = (await c.get("/auth/demo")).json()
    assert info == {"enabled": True, "label": "Тестовый доступ для Fintech Academy"}

    tokens = (await c.post("/auth/demo")).json()
    h = bearer(tokens["access_token"])
    me = (await c.get("/me", headers=h)).json()
    assert me["email"] == "jury@fintech-academy.demo" and me["demo"] is True

    accounts = (await c.get("/mail/accounts", headers=h)).json()
    assert [a["email"] for a in accounts] == ["dev@mail.example.com"]
    folders = await c.get(f"/mail/accounts/{accounts[0]['id']}/folders", headers=h)
    assert folders.status_code == 200, folders.text  # ящик действительно открывается

    projects = (await c.get("/platform/projects", headers=h)).json()
    assert projects["current_project_id"] == DEMO_PID

    # Гость отключил ящик — следующий вход вернёт его; дублей пользователей и ящиков нет.
    await c.delete(f"/mail/accounts/{accounts[0]['id']}", headers=h)
    again = await c.post("/auth/demo")
    assert again.status_code == 200
    assert len(await world.rows(User)) == 1
    assert len(await world.rows(MailAccount)) == 1


async def test_demo_email_cannot_be_registered_or_used_with_password(world, mail, monkeypatch):
    enable_demo(monkeypatch, mail, DEMO_PROJECT_CODE="")
    c = world.client
    taken = await c.post(
        "/auth/register", json={"email": "jury@fintech-academy.demo", "password": "x" * 12}
    )
    assert_error(taken, 409, "email_taken")
    assert (await c.post("/auth/demo")).status_code == 200
    login = await c.post(
        "/auth/login", json={"email": "jury@fintech-academy.demo", "password": "x" * 12}
    )
    assert_error(login, 401, "invalid_credentials")


async def test_demo_login_survives_platform_outage(world, mail, monkeypatch):
    enable_demo(monkeypatch, mail)
    world.platform.down = True
    r = await world.client.post("/auth/demo")
    assert r.status_code == 200, r.text
