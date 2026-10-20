"""Сборка и отправка письма по SMTP (stdlib smtplib, запускается через asyncio.to_thread)."""

import smtplib
import socket
import ssl
from contextlib import suppress
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app.services.mailbox.errors import auth_failed, rejected, unavailable

_NETWORK_ERRORS = (OSError, ssl.SSLError, smtplib.SMTPServerDisconnected)


@dataclass(frozen=True)
class SmtpConn:
    host: str
    port: int
    security: str  # ssl | starttls | none
    username: str
    password: str
    ip: str
    timeout: int


class _Smtp(smtplib.SMTP):
    def __init__(self, host: str, port: int, ip: str, timeout: int):
        self._ip = ip
        super().__init__(host, port, timeout=timeout)

    def _get_socket(self, host, port, timeout):
        return socket.create_connection((self._ip, port), timeout, self.source_address)


class _SmtpSSL(smtplib.SMTP_SSL):
    def __init__(self, host: str, port: int, ip: str, timeout: int, ctx: ssl.SSLContext):
        self._ip = ip
        super().__init__(host, port, timeout=timeout, context=ctx)

    def _get_socket(self, host, port, timeout):
        sock = socket.create_connection((self._ip, port), timeout, self.source_address)
        return self.context.wrap_socket(sock, server_hostname=self._host)


def _open(c: SmtpConn) -> smtplib.SMTP:
    ctx = ssl.create_default_context()
    try:
        if c.security == "ssl":
            smtp: smtplib.SMTP = _SmtpSSL(c.host, c.port, c.ip, c.timeout, ctx)
        else:
            smtp = _Smtp(c.host, c.port, c.ip, c.timeout)
            smtp.ehlo()
            if c.security == "starttls":
                smtp.starttls(context=ctx)
                smtp.ehlo()
    except _NETWORK_ERRORS + (smtplib.SMTPException,):
        raise unavailable() from None
    try:
        smtp.login(c.username, c.password)
    except smtplib.SMTPAuthenticationError:
        _quit(smtp)
        raise auth_failed() from None
    except smtplib.SMTPNotSupportedError:
        _quit(smtp)
        raise rejected() from None
    except _NETWORK_ERRORS + (smtplib.SMTPException,):
        _quit(smtp)
        raise unavailable() from None
    return smtp


def _quit(smtp: smtplib.SMTP) -> None:
    with suppress(Exception):  # закрытие не должно маскировать основную ошибку
        smtp.quit()


def check_login(c: SmtpConn) -> None:
    _quit(_open(c))


def send(c: SmtpConn, msg: EmailMessage, from_email: str, recipients: list[str]) -> None:
    smtp = _open(c)
    try:
        smtp.send_message(msg, from_addr=from_email, to_addrs=recipients)
    except smtplib.SMTPRecipientsRefused:
        raise rejected() from None
    except smtplib.SMTPSenderRefused:
        raise rejected() from None
    except smtplib.SMTPResponseException:
        raise rejected() from None
    except _NETWORK_ERRORS + (smtplib.SMTPException,):
        raise unavailable() from None
    finally:
        _quit(smtp)


@dataclass
class OutAttachment:
    filename: str
    content_type: str
    data: bytes


def build_message(
    *,
    from_email: str,
    display_name: str | None,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    text: str | None,
    html: str | None,
    attachments: list[OutAttachment],
    in_reply_to: str | None = None,
    references: str | None = None,
) -> EmailMessage:
    """Бросает ValueError, если в заголовках есть недопустимые символы (инъекция заголовков)."""
    msg = EmailMessage(policy=policy.SMTP)
    msg["From"] = formataddr((display_name or "", from_email))
    if to:
        msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_email.rsplit("@", 1)[-1])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    if text is not None and html is not None:
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
    elif html is not None:
        msg.set_content(html, subtype="html")
    else:
        msg.set_content(text or "")

    for att in attachments:
        maintype, _, subtype = att.content_type.partition("/")
        msg.add_attachment(
            att.data,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=att.filename,
        )
    return msg
