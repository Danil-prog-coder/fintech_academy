"""Сквозные сценарии почтового клиента против настоящих (локальных) IMAP и SMTP серверов."""

import base64
import logging
import socket
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formatdate

from app.core.security import decrypt_secret
from app.db.models import MailAccount
from tests.conftest import open_world
from tests.fake_mail import FakeMail
from tests.test_e2e import assert_error

PDF = b"%PDF-1.4 fake report bytes \x00\x01\x02"
PNG = b"\x89PNG\r\n\x1a\n fake logo"
HTML = (
    '<html><body><p>Hello <b>team</b></p><script>alert("xss1")</script>'
    '<img src="https://tracker.example/pixel.gif">'
    '<img src="cid:logo@x" onerror="alert(2)">'
    '<a href="javascript:alert(3)">bad</a><a href="https://ok.example/page">ok</a>'
    "</body></html>"
)


def make_mail(subject, sender, to, body, *, date=None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    msg["Date"] = date or formatdate()
    msg["Message-ID"] = f"<{abs(hash((subject, sender)))}@example.com>"
    msg.set_content(body)
    return msg


def rich_mail() -> bytes:
    msg = make_mail("Квартальный отчёт", "Борис <boris@example.com>", "dev@mail.example.com", "plain part")
    msg.add_alternative(HTML, subtype="html")
    msg.get_payload()[1].add_related(PNG, "image", "png", cid="<logo@x>")
    msg.add_attachment(PDF, maintype="application", subtype="pdf", filename="отчёт.pdf")
    return msg.as_bytes()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def account_body(mail: FakeMail, **override) -> dict:
    return {
        "email": "dev@mail.example.com",
        "password": mail.password,
        "display_name": "Разработчик",
        "imap_host": "127.0.0.1",
        "imap_port": mail.imap_port,
        "imap_security": "none",
        "smtp_host": "127.0.0.1",
        "smtp_port": mail.smtp_port,
        "smtp_security": "none",
        **override,
    }


async def seed_inbox(mail: FakeMail) -> dict[str, int]:
    uids = {
        "old": mail.add(
            "INBOX",
            make_mail(
                "Привет из прошлого", "Анна Петрова <anna@example.com>", "dev@mail.example.com",
                "Please check the roadmap before Friday.",
            ).as_bytes(),
        ),
        "rich": mail.add("INBOX", rich_mail()),
        "flagged": mail.add(
            "INBOX",
            make_mail("Счёт", "billing@example.com", "dev@mail.example.com", "invoice 42").as_bytes(),
            "\\Seen",
            "\\Flagged",
        ),
        "extra": mail.add(
            "INBOX", make_mail("Ещё одно", "x@example.com", "dev@mail.example.com", "tail").as_bytes()
        ),
    }
    return uids


async def test_mail_client_from_connect_to_send(world, mail, caplog):
    c = world.client
    caplog.set_level(logging.INFO)
    h = await world.user()

    # --- подключение ящика ------------------------------------------------------------
    no_hosts = await c.post(
        "/mail/accounts", json={"email": "dev@mail.example.com", "password": "x"}, headers=h
    )
    assert_error(no_hosts, 422, "mail_server_required")
    wrong = await c.post(
        "/mail/accounts", json=account_body(mail, password="wrong"), headers=h
    )
    assert_error(wrong, 400, "mail_auth_failed")
    dead = await c.post(
        "/mail/accounts", json=account_body(mail, imap_port=free_port()), headers=h
    )
    assert_error(dead, 502, "mail_unavailable", retryable=True)
    assert (await c.get("/mail/accounts", headers=h)).json() == []

    created = await c.post("/mail/accounts", json=account_body(mail), headers=h)
    assert created.status_code == 201, created.text
    acc = created.json()
    assert acc["email"] == "dev@mail.example.com" and acc["display_name"] == "Разработчик"
    assert mail.password not in created.text
    [row] = await world.rows(MailAccount)
    assert mail.password not in row.password_encrypted
    assert decrypt_secret(row.password_encrypted) == mail.password
    assert_error(
        await c.post("/mail/accounts", json=account_body(mail), headers=h), 409, "mail_account_exists"
    )
    assert [a["id"] for a in (await c.get("/mail/accounts", headers=h)).json()] == [acc["id"]]
    base = f"/mail/accounts/{acc['id']}"

    uids = await seed_inbox(mail)
    mail.add("Проекты", make_mail("Задачи проекта", "pm@example.com", "dev@mail.example.com", "todo").as_bytes())

    # --- папки ------------------------------------------------------------------------
    folders = (await c.get(f"{base}/folders", headers=h)).json()
    assert [f["role"] for f in folders] == ["inbox", "drafts", "sent", "trash", None]
    by_path = {f["path"]: f for f in folders}
    assert (by_path["INBOX"]["total"], by_path["INBOX"]["unseen"]) == (4, 3)
    assert by_path["Проекты"]["name"] == "Проекты" and by_path["Проекты"]["total"] == 1

    # --- список писем: порядок, страницы, фильтры, поиск, русская папка ------------------
    page = (await c.get(f"{base}/messages", headers=h)).json()
    assert page["total"] == 4 and page["folder"] == "INBOX"
    assert [m["uid"] for m in page["items"]] == [uids["extra"], uids["flagged"], uids["rich"], uids["old"]]
    by_uid = {m["uid"]: m for m in page["items"]}
    old = by_uid[uids["old"]]
    assert old["subject"] == "Привет из прошлого"
    assert old["sender"] == {"name": "Анна Петрова", "email": "anna@example.com"}
    assert old["to"] == [{"name": None, "email": "dev@mail.example.com"}]
    assert (old["seen"], old["flagged"], old["has_attachments"]) == (False, False, False)
    assert old["date"] and old["size"] > 0
    assert by_uid[uids["rich"]]["has_attachments"] is True
    assert (by_uid[uids["flagged"]]["seen"], by_uid[uids["flagged"]]["flagged"]) == (True, True)

    second = (await c.get(f"{base}/messages", params={"limit": 2, "offset": 2}, headers=h)).json()
    assert [m["uid"] for m in second["items"]] == [uids["rich"], uids["old"]] and second["total"] == 4
    unread = (await c.get(f"{base}/messages", params={"unread": True}, headers=h)).json()
    assert unread["total"] == 3 and uids["flagged"] not in [m["uid"] for m in unread["items"]]
    search = f"{base}/messages/search"
    found = (await c.post(search, json={"q": "roadmap"}, headers=h)).json()
    assert [m["uid"] for m in found["items"]] == [uids["old"]]
    assert (await c.post(search, json={"q": "нет такого слова"}, headers=h)).json()["total"] == 0
    unread_hit = (await c.post(search, json={"q": "invoice", "unread": True}, headers=h)).json()
    assert unread_hit["total"] == 0  # письмо со счётом уже прочитано
    projects = (await c.get(f"{base}/messages", params={"folder": "Проекты"}, headers=h)).json()
    assert [m["subject"] for m in projects["items"]] == ["Задачи проекта"]
    assert_error(
        await c.get(f"{base}/messages", params={"folder": "Нет такой"}, headers=h),
        404,
        "folder_not_found",
    )

    # --- чтение: помечается прочитанным, mark_read=false не трогает флаги -----------------
    peek = (await c.get(f"{base}/messages/{uids['old']}", params={"mark_read": False}, headers=h)).json()
    assert peek["seen"] is False and "\\Seen" not in mail.find("INBOX", uids["old"]).flags
    msg = (await c.get(f"{base}/messages/{uids['old']}", headers=h)).json()
    assert msg["seen"] is True and "\\Seen" in mail.find("INBOX", uids["old"]).flags
    assert msg["text"].strip() == "Please check the roadmap before Friday."
    assert msg["html"] is None and msg["attachments"] == []
    assert msg["subject"] == "Привет из прошлого" and msg["message_id"].startswith("<")

    # HTML очищается: скрипты, обработчики, javascript: и внешние картинки вырезаны.
    rich = (await c.get(f"{base}/messages/{uids['rich']}", headers=h)).json()
    html = rich["html"]
    for forbidden in ("<script", "xss1", "onerror", "javascript:", "tracker.example"):
        assert forbidden not in html, forbidden
    assert "cid:logo@x" in html and "https://ok.example/page" in html and "<b>team</b>" in html
    assert rich["remote_images_blocked"] is True and rich["text"].strip() == "plain part"
    assert [(a["filename"], a["content_type"], a["inline"]) for a in rich["attachments"]] == [
        ("attachment-1", "image/png", True),
        ("отчёт.pdf", "application/pdf", False),
    ]
    assert rich["attachments"][0]["content_id"] == "logo@x"
    pdf = next(a for a in rich["attachments"] if a["filename"] == "отчёт.pdf")
    assert pdf["size"] == len(PDF)

    download = await c.get(
        f"{base}/messages/{uids['rich']}/attachments/{pdf['index']}", headers=h
    )
    assert download.status_code == 200 and download.content == PDF
    assert download.headers["content-type"] == "application/pdf"
    assert "filename*=UTF-8''" in download.headers["content-disposition"]
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["content-security-policy"] == "sandbox"
    assert_error(
        await c.get(f"{base}/messages/{uids['rich']}/attachments/9", headers=h),
        404,
        "attachment_not_found",
    )
    assert_error(await c.get(f"{base}/messages/9999", headers=h), 404, "message_not_found")

    # --- управление: флаги, перенос, удаление ------------------------------------------
    patch = await c.patch(
        f"{base}/messages/{uids['old']}", json={"seen": False, "flagged": True}, headers=h
    )
    assert patch.status_code == 204
    flags = {f.lower() for f in mail.find("INBOX", uids["old"]).flags}
    assert flags == {"\\flagged"}
    moved = await c.patch(
        f"{base}/messages/{uids['old']}", json={"move_to": "Проекты"}, headers=h
    )
    assert moved.status_code == 204
    assert mail.find("INBOX", uids["old"]) is None and len(mail.uids("Проекты")) == 2
    assert_error(
        await c.patch(f"{base}/messages/{uids['extra']}", json={"move_to": "Нигде"}, headers=h),
        404,
        "folder_not_found",
    )
    assert_error(
        await c.patch(f"{base}/messages/9999", json={"seen": True}, headers=h), 404, "message_not_found"
    )

    assert (await c.delete(f"{base}/messages/{uids['extra']}", headers=h)).status_code == 204
    assert mail.find("INBOX", uids["extra"]) is None and len(mail.uids("Trash")) == 1
    trashed = mail.uids("Trash")[0]
    assert (await c.delete(f"{base}/messages/{trashed}", params={"folder": "Trash"}, headers=h)).status_code == 204
    assert mail.uids("Trash") == []  # из корзины — безвозвратно
    assert (
        await c.delete(f"{base}/messages/{uids['flagged']}", params={"permanent": True}, headers=h)
    ).status_code == 204
    assert mail.find("INBOX", uids["flagged"]) is None and mail.uids("Trash") == []
    assert_error(await c.delete(f"{base}/messages/9999", headers=h), 404, "message_not_found")

    # --- отправка ----------------------------------------------------------------------
    original = uids["rich"]
    sent = await c.post(
        f"{base}/send",
        json={
            "to": ["boris@example.com"],
            "cc": ["cc@example.com"],
            "bcc": ["hidden@example.com"],
            "subject": "Re: Квартальный отчёт",
            "text": "Спасибо, смотрю.",
            "html": "<p>Спасибо, <i>смотрю</i>.</p>",
            "attachments": [
                {
                    "filename": "заметки.txt",
                    "content_type": "text/plain",
                    "content_base64": base64.b64encode("привет".encode()).decode(),
                }
            ],
            "in_reply_to": rich["message_id"],
            "references": rich["message_id"],
            "answered": {"folder": "INBOX", "uid": original},
        },
        headers=h,
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["saved_to_sent"] is True
    [(env_from, env_rcpts, data)] = mail.smtp_inbox
    assert env_from == "dev@mail.example.com"
    assert sorted(env_rcpts) == ["boris@example.com", "cc@example.com", "hidden@example.com"]
    out = message_from_bytes(data, policy=policy.default)
    assert str(out["From"]) == "Разработчик <dev@mail.example.com>"
    assert str(out["To"]) == "boris@example.com" and str(out["Cc"]) == "cc@example.com"
    assert out["Bcc"] is None  # скрытая копия не раскрывается получателям
    assert str(out["Subject"]) == "Re: Квартальный отчёт" and str(out["In-Reply-To"]) == rich["message_id"]
    assert out["Message-ID"] == sent.json()["message_id"]
    assert out.get_body(("plain",)).get_content().strip() == "Спасибо, смотрю."
    assert "<i>смотрю</i>" in out.get_body(("html",)).get_content()
    [attached] = list(out.iter_attachments())
    assert attached.get_filename() == "заметки.txt" and attached.get_payload(decode=True) == "привет".encode()
    # Копия легла в «Отправленные», исходное письмо помечено отвеченным.
    [copy_uid] = mail.uids("Sent")
    assert "\\Seen" in mail.find("Sent", copy_uid).flags
    assert "\\Answered" in mail.find("INBOX", original).flags

    # Ошибки отправки: ничего не уходит и не сохраняется.
    mail.smtp_rejects.add("nobody@example.com")
    refused = await c.post(f"{base}/send", json={"to": ["nobody@example.com"], "text": "x"}, headers=h)
    assert_error(refused, 502, "mail_rejected")
    assert len(mail.smtp_inbox) == 1 and mail.uids("Sent") == [copy_uid]
    assert_error(await c.post(f"{base}/send", json={"text": "x"}, headers=h), 422, "no_recipients")
    assert_error(
        await c.post(f"{base}/send", json={"to": ["a@example.com"]}, headers=h), 422, "empty_message"
    )
    assert_error(
        await c.post(
            f"{base}/send",
            json={"to": ["a@example.com"], "subject": "hi\r\nBcc: evil@example.com", "text": "x"},
            headers=h,
        ),
        422,
        "invalid_message",
    )
    assert_error(
        await c.post(
            f"{base}/send",
            json={
                "to": ["a@example.com"],
                "attachments": [{"filename": "a.bin", "content_base64": "###"}],
            },
            headers=h,
        ),
        422,
        "invalid_attachment",
    )
    assert len(mail.smtp_inbox) == 1

    # --- черновик ----------------------------------------------------------------------
    draft = await c.post(
        f"{base}/drafts", json={"subject": "Позже", "text": "недописано"}, headers=h
    )
    assert draft.status_code == 201 and draft.json()["folder"] == "Drafts"
    [draft_uid] = mail.uids("Drafts")
    assert {"\\Draft", "\\Seen"} <= mail.find("Drafts", draft_uid).flags
    assert len(mail.smtp_inbox) == 1  # черновик не отправляется

    # --- изоляция и отключение ---------------------------------------------------------
    h2 = await world.user("other@example.com")
    for method, path in [
        ("GET", base + "/folders"),
        ("GET", base + "/messages"),
        ("POST", base + "/messages/search"),
        ("GET", f"{base}/messages/{original}"),
        ("PATCH", f"{base}/messages/{original}"),
        ("DELETE", f"{base}/messages/{original}"),
        ("POST", base + "/send"),
        ("POST", base + "/drafts"),
        ("DELETE", base),
    ]:
        r = await c.request(method, path, json={"to": ["a@example.com"], "text": "x", "q": "x"}, headers=h2)
        assert_error(r, 404, "mail_account_not_found")
        assert_error(await c.request(method, path), 401, "unauthorized")
    assert (await c.get("/mail/accounts", headers=h2)).json() == []
    assert len(mail.smtp_inbox) == 1

    # --- ни пароль, ни содержимое писем не попали в логи ---------------------------------
    server_logs = "\n".join(r.getMessage() for r in caplog.records if r.name != "httpx")
    for secret in (mail.password, "roadmap", "Квартальный", "Спасибо, смотрю", "hidden@example.com"):
        assert secret not in server_logs, secret

    assert (await c.delete(base, headers=h)).status_code == 204
    assert (await c.get("/mail/accounts", headers=h)).json() == []
    assert_error(await c.get(f"{base}/folders", headers=h), 404, "mail_account_not_found")


async def test_mail_client_on_server_without_move_and_uidplus(world):
    """Старый сервер: перенос и удаление идут через COPY + \\Deleted + EXPUNGE."""
    legacy = await FakeMail(move=False, uidplus=False).start()
    try:
        c = world.client
        h = await world.user()
        acc = (await c.post("/mail/accounts", json=account_body(legacy), headers=h)).json()
        base = f"/mail/accounts/{acc['id']}"
        keep = legacy.add("INBOX", make_mail("Остаётся", "a@example.com", "dev@mail.example.com", "keep").as_bytes())
        gone = legacy.add("INBOX", make_mail("Уходит", "b@example.com", "dev@mail.example.com", "gone").as_bytes())
        also = legacy.add("INBOX", make_mail("Переносим", "c@example.com", "dev@mail.example.com", "mv").as_bytes())

        assert (await c.patch(f"{base}/messages/{also}", json={"move_to": "Проекты"}, headers=h)).status_code == 204
        assert (await c.delete(f"{base}/messages/{gone}", headers=h)).status_code == 204
        assert legacy.uids("INBOX") == [keep]
        assert len(legacy.uids("Проекты")) == 1 and len(legacy.uids("Trash")) == 1
        # В корзине копия не должна остаться помеченной удалённой.
        assert "\\Deleted" not in legacy.find("Trash", legacy.uids("Trash")[0]).flags
    finally:
        await legacy.stop()


async def test_mail_connection_is_protected_from_ssrf(monkeypatch, tmp_path, mail):
    """Без разрешения приватных адресов сервер не ходит ни на localhost, ни во внутреннюю сеть."""
    async with open_world(monkeypatch, tmp_path, mail_private=False) as w:
        h = await w.user()
        targets = ["127.0.0.1", "localhost", "10.0.0.5", "192.168.1.10", "169.254.169.254", "::1"]
        for host in targets:
            r = await w.client.post(
                "/mail/accounts",
                json=account_body(mail, imap_host=host, imap_security="ssl", smtp_security="ssl"),
                headers=h,
            )
            assert_error(r, 400, "mail_host_forbidden")
        # Соединение без шифрования запрещено, даже если адрес внешний.
        plain = await w.client.post(
            "/mail/accounts",
            json=account_body(mail, imap_host="93.184.216.34", imap_security="none"),
            headers=h,
        )
        assert_error(plain, 400, "mail_host_forbidden")
        assert mail.imap_logins == 0 and await w.rows(MailAccount) == []


async def test_mail_connects_when_only_smtp_is_unreachable(world, mail):
    """Хостинг может закрыть исходящие SMTP-порты: читать почту это не мешает."""
    c = world.client
    h = await world.user()
    port = free_port()
    created = await c.post("/mail/accounts", json=account_body(mail, smtp_port=port), headers=h)
    assert created.status_code == 201, created.text

    sent = await c.post(
        f"/mail/accounts/{created.json()['id']}/send",
        json={"to": ["a@example.com"], "text": "x"},
        headers=h,
    )
    assert_error(sent, 502, "mail_unavailable", retryable=True)
    assert f"SMTP-серверу 127.0.0.1:{port}" in sent.json()["message"]

    # Неверный пароль по-прежнему не даёт сохранить ящик.
    wrong = await c.post(
        "/mail/accounts",
        json=account_body(mail, email="other@mail.example.com", password="wrong", smtp_port=port),
        headers=h,
    )
    assert_error(wrong, 400, "mail_auth_failed")
