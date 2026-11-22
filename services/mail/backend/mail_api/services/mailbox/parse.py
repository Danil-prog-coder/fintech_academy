"""Разбор писем (stdlib email) и безопасная подготовка HTML для показа."""

import html as html_lib
import re
from dataclasses import dataclass, field
from datetime import datetime
from email import message_from_bytes, policy
from email.message import EmailMessage, Message

import nh3

SNIPPET_CHARS = 140
_REMOTE_URL = re.compile(r"^\s*(https?:)?//", re.IGNORECASE)
_REMOTE_IMG_IN_HTML = re.compile(r"<img\b[^>]*\bsrc\s*=\s*[\"']?\s*(https?:)?//", re.IGNORECASE)


@dataclass
class Address:
    name: str | None
    email: str


@dataclass
class AttachmentInfo:
    index: int
    filename: str
    content_type: str
    size: int
    inline: bool
    content_id: str | None


@dataclass
class Parsed:
    subject: str = ""
    sender: Address | None = None
    to: list[Address] = field(default_factory=list)
    cc: list[Address] = field(default_factory=list)
    date: datetime | None = None
    message_id: str | None = None
    in_reply_to: str | None = None
    references: str | None = None
    has_attachments: bool = False


def _addresses(msg: Message, name: str) -> list[Address]:
    out: list[Address] = []
    for header in msg.get_all(name, []):
        try:
            for a in header.addresses:
                if a.addr_spec:
                    out.append(Address(name=a.display_name or None, email=a.addr_spec))
        except (AttributeError, ValueError):
            continue  # битый заголовок не должен ломать список писем
    return out


def _text_header(msg: Message, name: str) -> str | None:
    value = msg.get(name)
    return str(value).strip() if value is not None else None


def parse_headers(raw: bytes) -> Parsed:
    msg = message_from_bytes(raw, policy=policy.default)
    senders = _addresses(msg, "from")
    date = None
    try:
        header = msg.get("date")
        date = header.datetime if header is not None else None
    except (AttributeError, ValueError, TypeError):
        date = None
    content_type = (msg.get_content_type() or "").lower()
    return Parsed(
        subject=str(msg.get("subject", "") or ""),
        sender=senders[0] if senders else None,
        to=_addresses(msg, "to"),
        cc=_addresses(msg, "cc"),
        date=date,
        message_id=_text_header(msg, "message-id"),
        in_reply_to=_text_header(msg, "in-reply-to"),
        references=_text_header(msg, "references"),
        has_attachments=content_type in ("multipart/mixed", "multipart/signed"),
    )


def html_to_text(html: str) -> str:
    stripped = nh3.clean(html, tags=set(), clean_content_tags={"script", "style", "head"})
    return re.sub(r"\s+", " ", html_lib.unescape(stripped)).strip()


def snippet_of(text: str | None, html: str | None) -> str:
    source = text if text else (html_to_text(html) if html else "")
    source = re.sub(r"\s+", " ", source).strip()
    return source[:SNIPPET_CHARS]


def _drop_remote_images(tag: str, attr: str, value: str) -> str | None:
    """Внешние картинки — трекинговые пиксели и утечка IP: не загружаем без явного согласия."""
    if tag == "img" and attr == "src" and _REMOTE_URL.match(value):
        return None
    return value


def sanitize_html(html: str) -> tuple[str, bool]:
    """Возвращает безопасный HTML и признак, что внешние картинки были вырезаны."""
    remote = bool(_REMOTE_IMG_IN_HTML.search(html))
    cleaned = nh3.clean(
        html,
        url_schemes=set(nh3.ALLOWED_URL_SCHEMES) | {"cid"},
        attribute_filter=_drop_remote_images,
        link_rel="noopener noreferrer nofollow",
    )
    return cleaned, remote


@dataclass
class FullMessage:
    parsed: Parsed
    text: str | None
    html: str | None
    remote_images_blocked: bool
    attachments: list[AttachmentInfo]


def _decoded_content(part: EmailMessage) -> str | None:
    try:
        return part.get_content()
    except (LookupError, ValueError, UnicodeError):
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", "replace")


def _is_attachment(part: Message) -> bool:
    disposition = part.get_content_disposition()
    if disposition == "attachment" or part.get_filename():
        return True
    # Встроенные части (картинки в письме) нужны, чтобы раскрыть cid:
    return disposition == "inline" and part.get_content_maintype() not in ("text", "multipart")


def iter_attachments(msg: EmailMessage):
    """(индекс, часть) в порядке обхода; индекс стабилен для скачивания."""
    index = 0
    for part in msg.walk():
        if part.is_multipart():
            continue
        if _is_attachment(part):
            yield index, part
            index += 1


def parse_full(raw: bytes) -> tuple[FullMessage, EmailMessage]:
    msg = message_from_bytes(raw, policy=policy.default)
    parsed = parse_headers(raw)

    text_part = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    text = _decoded_content(text_part) if text_part is not None else None
    html = None
    blocked = False
    if html_part is not None:
        source = _decoded_content(html_part)
        if source:
            html, blocked = sanitize_html(source)

    attachments: list[AttachmentInfo] = []
    for index, part in iter_attachments(msg):
        payload = part.get_payload(decode=True) or b""
        content_id = part.get("content-id")
        attachments.append(
            AttachmentInfo(
                index=index,
                filename=part.get_filename() or f"attachment-{index + 1}",
                content_type=part.get_content_type(),
                size=len(payload),
                inline=part.get_content_disposition() == "inline",
                content_id=str(content_id).strip("<> ") if content_id else None,
            )
        )
    parsed.has_attachments = any(not a.inline for a in attachments)
    return FullMessage(parsed, text, html, blocked, attachments), msg
