"""Настройки серверов и защита от SSRF.

Пользователь сам указывает, к какому серверу подключаться, поэтому без проверки он мог бы
заставить backend ходить во внутреннюю сеть. Имя сервера резолвится один раз, все адреса
должны быть публичными, а соединение идёт на проверенный IP (защита от DNS rebinding).
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.errors import AppError

SECURITIES = ("ssl", "starttls", "none")


@dataclass(frozen=True)
class ServerSettings:
    imap_host: str
    imap_port: int
    imap_security: str
    smtp_host: str
    smtp_port: int
    smtp_security: str


def _preset(imap: str, smtp: str, smtp_port: int = 465, smtp_sec: str = "ssl") -> ServerSettings:
    return ServerSettings(imap, 993, "ssl", smtp, smtp_port, smtp_sec)


_GMAIL = _preset("imap.gmail.com", "smtp.gmail.com")
_YANDEX = _preset("imap.yandex.ru", "smtp.yandex.ru")
_MAILRU = _preset("imap.mail.ru", "smtp.mail.ru")
_OUTLOOK = _preset("outlook.office365.com", "smtp-mail.outlook.com", 587, "starttls")
_ICLOUD = _preset("imap.mail.me.com", "smtp.mail.me.com", 587, "starttls")
_RAMBLER = _preset("imap.rambler.ru", "smtp.rambler.ru")

PRESETS: dict[str, ServerSettings] = {
    **dict.fromkeys(("gmail.com", "googlemail.com"), _GMAIL),
    **dict.fromkeys(("yandex.ru", "yandex.com", "ya.ru", "yandex.by", "yandex.kz"), _YANDEX),
    **dict.fromkeys(("mail.ru", "inbox.ru", "list.ru", "bk.ru", "internet.ru"), _MAILRU),
    **dict.fromkeys(("outlook.com", "hotmail.com", "live.com", "msn.com"), _OUTLOOK),
    **dict.fromkeys(("icloud.com", "me.com", "mac.com"), _ICLOUD),
    "rambler.ru": _RAMBLER,
}


def server_settings(
    email: str,
    imap_host: str | None,
    imap_port: int | None,
    imap_security: str | None,
    smtp_host: str | None,
    smtp_port: int | None,
    smtp_security: str | None,
) -> ServerSettings:
    """Явные значения важнее пресета по домену ящика."""
    preset = PRESETS.get(email.rsplit("@", 1)[-1].lower())
    if preset is None and not (imap_host and smtp_host):
        raise AppError(
            "mail_server_required",
            "Для этого почтового домена укажите адреса IMAP- и SMTP-серверов.",
            422,
        )
    base = preset or ServerSettings(imap_host or "", 993, "ssl", smtp_host or "", 465, "ssl")
    return ServerSettings(
        imap_host=imap_host or base.imap_host,
        imap_port=imap_port or base.imap_port,
        imap_security=imap_security or base.imap_security,
        smtp_host=smtp_host or base.smtp_host,
        smtp_port=smtp_port or base.smtp_port,
        smtp_security=smtp_security or base.smtp_security,
    )


def saves_sent_copy(smtp_host: str) -> bool:
    """Gmail сам кладёт отправленное в «Отправленные»; второй копии добавлять не нужно."""
    return smtp_host.lower().endswith("gmail.com")


def _forbidden(message: str) -> AppError:
    return AppError("mail_host_forbidden", message, 400)


async def resolve_public_host(host: str, port: int, security: str) -> str:
    """Возвращает IP для подключения или бросает mail_host_forbidden."""
    allow_private = get_settings().mail_allow_private_hosts
    if security not in SECURITIES:
        raise _forbidden("Неизвестный режим защиты соединения.")
    if security == "none" and not allow_private:
        raise _forbidden("Соединение без шифрования запрещено.")
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, port, type=socket.SOCK_STREAM
        )
    except OSError:
        raise AppError(
            "mail_unavailable", "Не удалось найти почтовый сервер.", 502, retryable=False
        ) from None
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise AppError("mail_unavailable", "Не удалось найти почтовый сервер.", 502)
    if not allow_private:
        for addr in addresses:
            if not ipaddress.ip_address(addr.split("%", 1)[0]).is_global:
                raise _forbidden("Адрес почтового сервера недопустим.")
    return addresses[0]
