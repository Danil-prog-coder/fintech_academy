from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

Security = Literal["ssl", "starttls", "none"]


class AccountCreate(BaseModel):
    """Подключение ящика по IMAP/SMTP. Для известных доменов серверы подставляются сами."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=256, description="Пароль приложения.")
    display_name: str | None = Field(default=None, max_length=200)
    username: str | None = Field(default=None, max_length=320, description="По умолчанию = email.")
    imap_host: str | None = Field(default=None, max_length=255)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_security: Security | None = None
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_security: Security | None = None


class AccountOut(BaseModel):
    id: int
    email: str
    display_name: str | None
    imap_host: str
    smtp_host: str
    created_at: datetime


class FolderOut(BaseModel):
    path: str = Field(description="Полное имя; его передают в параметр folder.")
    name: str
    role: Literal["inbox", "sent", "drafts", "trash", "junk", "archive"] | None
    total: int
    unseen: int


class AddressOut(BaseModel):
    name: str | None
    email: str


class MessageSummary(BaseModel):
    uid: int
    subject: str
    sender: AddressOut | None
    to: list[AddressOut]
    date: datetime | None
    snippet: str | None = Field(description="Короткий фрагмент; в списке не заполняется.")
    seen: bool
    flagged: bool
    answered: bool
    draft: bool
    has_attachments: bool
    size: int


class MessageList(BaseModel):
    folder: str
    total: int
    items: list[MessageSummary]


class AttachmentOut(BaseModel):
    index: int = Field(description="Номер для скачивания вложения.")
    filename: str
    content_type: str
    size: int
    inline: bool
    content_id: str | None


class MessageOut(BaseModel):
    uid: int
    folder: str
    message_id: str | None
    in_reply_to: str | None
    references: str | None
    subject: str
    sender: AddressOut | None
    to: list[AddressOut]
    cc: list[AddressOut]
    date: datetime | None
    seen: bool
    flagged: bool
    answered: bool
    text: str | None
    html: str | None = Field(
        description="Очищенный HTML (без скриптов и внешних картинок). Показывать в изолированном контейнере."
    )
    remote_images_blocked: bool
    attachments: list[AttachmentOut]


class SearchRequest(BaseModel):
    q: str = Field(min_length=1, max_length=200, description="Текст для поиска по письмам.")
    folder: str = Field(default="INBOX", max_length=500)
    unread: bool = False
    limit: int = Field(default=30, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class MessagePatch(BaseModel):
    seen: bool | None = None
    flagged: bool | None = None
    move_to: str | None = Field(default=None, max_length=500, description="Путь папки назначения.")


class OutgoingAttachment(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="application/octet-stream", max_length=200)
    content_base64: str = Field(description="Содержимое файла в base64.")


class ReplyTarget(BaseModel):
    folder: str
    uid: int


class SendRequest(BaseModel):
    to: list[EmailStr] = Field(default_factory=list, max_length=100)
    cc: list[EmailStr] = Field(default_factory=list, max_length=100)
    bcc: list[EmailStr] = Field(default_factory=list, max_length=100)
    subject: str = Field(default="", max_length=998)
    text: str | None = Field(default=None, max_length=1_000_000)
    html: str | None = Field(default=None, max_length=2_000_000)
    attachments: list[OutgoingAttachment] = Field(default_factory=list, max_length=20)
    in_reply_to: str | None = Field(default=None, max_length=998)
    references: str | None = Field(default=None, max_length=4000)
    answered: ReplyTarget | None = Field(
        default=None, description="Исходное письмо: после отправки получит флаг «отвечено»."
    )


class SendResult(BaseModel):
    message_id: str
    saved_to_sent: bool


class DraftResult(BaseModel):
    message_id: str
    folder: str
