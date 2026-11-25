"""Мелкие правила почтового клиента без сети: роли папок и запасной порт SMTP."""

import asyncio
from types import SimpleNamespace

import pytest

from mail_api.api import mailbox as api
from mail_api.core.errors import AppError
from mail_api.services.mailbox import imap
from mail_api.services.mailbox.errors import unavailable, unreachable


def folder(path: str, *flags: str) -> imap.RawFolder:
    f = imap.RawFolder(path=path, delimiter="/", flags={x.lower() for x in flags})
    f.role = imap.folder_role(path, f.flags)
    return f


def test_gmail_service_folders_get_roles():
    roles = {
        f.path: f.role
        for f in [
            folder("[Gmail]/Вся почта", "\\All"),
            folder("[Gmail]/Помеченные", "\\Flagged"),
            folder("[Gmail]/Важное", "\\Important"),
            folder("[Gmail]/Отправленные", "\\Sent"),
        ]
    }
    assert roles == {
        "[Gmail]/Вся почта": "all",
        "[Gmail]/Помеченные": "flagged",
        "[Gmail]/Важное": "important",
        "[Gmail]/Отправленные": "sent",
    }


def test_role_goes_to_flagged_folder_only():
    """Две «Черновики» в боковой панели: роль достаётся папке с флагом \\Drafts."""
    by_name = folder("Drafts")
    by_flag = folder("[Gmail]/Черновики", "\\Drafts")
    result = imap._dedupe_roles([by_name, by_flag])
    assert [f.role for f in result] == [None, "drafts"]


class _Session:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


def _account(port: int, security: str):
    return SimpleNamespace(
        email="me@gmail.com", smtp_host="smtp.gmail.com", smtp_port=port, smtp_security=security
    )


def _conn(account):
    return api.smtp.SmtpConn(
        host=account.smtp_host,
        port=account.smtp_port,
        security=account.smtp_security,
        username="u",
        password="p",
        ip="203.0.113.1",
        timeout=1,
    )


@pytest.fixture
def no_dns(monkeypatch):
    async def fake_conn(account):
        return _conn(account)

    monkeypatch.setattr(api, "_smtp_conn", fake_conn)


def test_smtp_falls_back_to_second_port_and_remembers_it(monkeypatch, no_dns):
    tried = []

    def send(c, *_):
        tried.append(c.port)
        if c.port == 465:
            raise unreachable()

    monkeypatch.setattr(api.smtp, "send", send)
    account, session = _account(465, "ssl"), _Session()
    asyncio.run(api._smtp_send(session, account, object(), ["a@example.com"]))
    assert tried == [465, 587]
    assert (account.smtp_port, account.smtp_security) == (587, "starttls")
    assert session.commits == 1


def test_smtp_reports_both_ports_when_hosting_blocks_them(monkeypatch, no_dns):
    def send(c, *_):
        raise unreachable()

    monkeypatch.setattr(api.smtp, "send", send)
    with pytest.raises(AppError) as err:
        asyncio.run(api._smtp_send(_Session(), _account(465, "ssl"), object(), ["a@b.c"]))
    assert err.value.code == "mail_unavailable"
    assert "465" in err.value.message and "587" in err.value.message


def test_smtp_does_not_resend_after_connection_dropped_mid_send(monkeypatch, no_dns):
    """Обрыв уже после соединения: письмо могло уйти, второй попытки нет."""
    tried = []

    def send(c, *_):
        tried.append(c.port)
        raise unavailable()

    monkeypatch.setattr(api.smtp, "send", send)
    with pytest.raises(AppError) as err:
        asyncio.run(api._smtp_send(_Session(), _account(465, "ssl"), object(), ["a@b.c"]))
    assert tried == [465]
    assert "smtp.gmail.com:465" in err.value.message
