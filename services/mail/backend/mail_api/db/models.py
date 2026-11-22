from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MailAccount(Base):
    """Подключённый почтовый ящик (IMAP/SMTP). Письма не хранятся: читаем с сервера почты."""

    __tablename__ = "mail_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    username: Mapped[str] = mapped_column(String(320))
    password_encrypted: Mapped[str] = mapped_column(Text)
    imap_host: Mapped[str] = mapped_column(String(255))
    imap_port: Mapped[int] = mapped_column(default=993)
    imap_security: Mapped[str] = mapped_column(String(10), default="ssl")  # ssl | starttls | none
    smtp_host: Mapped[str] = mapped_column(String(255))
    smtp_port: Mapped[int] = mapped_column(default=465)
    smtp_security: Mapped[str] = mapped_column(String(10), default="ssl")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PlatformLink(Base):
    """The project the user works in right now (the platform keeps projects and statuses; we keep only the choice)."""

    __tablename__ = "platform_links"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    current_project_id: Mapped[str | None] = mapped_column(String(8), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class PlatformCursor(Base):
    """Cursor of the platform's event feed (GET /v1/events?after=…): one row."""

    __tablename__ = "platform_cursor"

    id: Mapped[int] = mapped_column(primary_key=True)
    after: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Notification(Base):
    """An event of the platform addressed to one of our users: an admin's answer, a support reply, …"""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    type: Mapped[str] = mapped_column(String(48))
    project_id: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
