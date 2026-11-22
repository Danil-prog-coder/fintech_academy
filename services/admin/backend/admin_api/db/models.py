"""Data model of the platform core.

Identity is the integrator's: a member is `(project, external_id)` — the id the integrating service uses for its own
user. The platform stores no personal data beyond an optional display name and the login of panel accounts.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base, UTCDateTime, utc_now

# BigInteger primary keys on Postgres, plain INTEGER on SQLite (autoincrement works only there)
BigId = BigInteger().with_variant(Integer, "sqlite")


class Role(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    SUPPORT = "support"
    USER = "user"

    @property
    def has_panel(self) -> bool:
        return self in (Role.OWNER, Role.ADMIN, Role.SUPPORT)

    @property
    def is_manager(self) -> bool:
        return self in (Role.OWNER, Role.ADMIN)


class Integration(Base):
    """A service that integrates the platform (a mail client, a messenger bot, a portal)."""

    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_prefix: Mapped[str] = mapped_column(String(16))
    webhook_url: Mapped[str | None] = mapped_column(String(512))
    webhook_secret_enc: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(8), unique=True)  # the id in the API and in the project code
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    code_hash: Mapped[str] = mapped_column(String(256))
    code_enc: Mapped[str] = mapped_column(Text)  # the owner sees the code in the panel at any time
    code_issued_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    @property
    def rag_project_id(self) -> str:
        return f"p-{self.public_id}"


class Section(Base):
    """Documentation section of a project («general», «security»…); a member may be limited to some sections."""

    __tablename__ = "sections"
    __table_args__ = (UniqueConstraint("project_id", "slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("project_id", "external_id"), Index("ix_members_project_role", "project_id", "role"))

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str | None] = mapped_column(String(128))
    # None — every section is open; a list — only these section slugs (owners and admins always see everything)
    allowed_sections: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)

    account: Mapped[PanelAccount | None] = relationship(back_populates="member", uselist=False, lazy="selectin",
                                                        cascade="all, delete-orphan")


class SiteUser(Base):
    """An account on the site: login + password, registered by the person. Access to projects — `PanelAccount`."""

    __tablename__ = "site_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class PanelAccount(Base):
    """Access of a site account to one project (owner / admin / support).

    Created either on the site (project created or joined as admin with the project code) or by an integration that
    assigned the status; then the person links it to their site account by a one-time link (`SetupToken`).
    `login` is only a label until then: the login on the site is `SiteUser.login`.
    """

    __tablename__ = "panel_accounts"
    __table_args__ = (UniqueConstraint("project_id", "login"), UniqueConstraint("user_id", "project_id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), unique=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("site_users.id", ondelete="SET NULL"))
    login: Mapped[str] = mapped_column(String(64))
    # legacy: the per-project password from before site accounts (migrated into site_users), not used any more
    password_hash: Mapped[str | None] = mapped_column(String(256))
    password_set_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    member: Mapped[Member] = relationship(back_populates="account", lazy="selectin")
    user: Mapped[SiteUser | None] = relationship(lazy="selectin")


class SetupToken(Base):
    """One-time link that attaches a panel account (status given by an integration) to a site account."""

    __tablename__ = "setup_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("panel_accounts.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class PanelSession(Base):
    """A signed-in site account; `account_id` — the project chosen right now (None — the project picker)."""

    __tablename__ = "panel_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("site_users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("panel_accounts.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Turn(Base):
    """One answered question: the journal behind statistics, ratings and the «unanswered» queue."""

    __tablename__ = "turns"
    __table_args__ = (Index("ix_turns_project_created", "project_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    external_id: Mapped[str] = mapped_column(String(128))
    channel: Mapped[str | None] = mapped_column(String(32))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class QuestionStatus(enum.StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    DISMISSED = "dismissed"


class Question(Base):
    """A question the documentation did not answer: it goes to the project's owner and admins."""

    __tablename__ = "questions"
    __table_args__ = (Index("ix_questions_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    external_id: Mapped[str] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    text: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(16))  # no_answer | dislike
    status: Mapped[str] = mapped_column(String(16), default=QuestionStatus.PENDING)
    answer: Mapped[str | None] = mapped_column(Text)
    answered_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    saved_to_kb: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class EscalationStatus(enum.StrEnum):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    WAITING_CUSTOMER = "waiting_customer"
    RESOLVED = "resolved"
    CLOSED = "closed"

    @property
    def is_open(self) -> bool:
        return self not in (EscalationStatus.RESOLVED, EscalationStatus.CLOSED)


class Escalation(Base):
    """A support ticket (ТП). Mirrored to Jira when the project has Jira configured."""

    __tablename__ = "escalations"
    __table_args__ = (Index("ix_escalations_project_status", "project_id", "status"),
                      Index("ix_escalations_jira_state", "jira_state", "jira_next_at"))

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(24), default=EscalationStatus.WAITING)
    priority: Mapped[str] = mapped_column(String(16), default="Medium")
    reason: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    history: Mapped[list] = mapped_column(JSON, default=list)
    request_id: Mapped[str | None] = mapped_column(String(64))
    assignee_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    user_rating: Mapped[int | None] = mapped_column(SmallInteger)
    # Jira mirror: none (project has no Jira) | pending (to create) | created | failed (gave up after retries)
    jira_state: Mapped[str] = mapped_column(String(16), default="none")
    jira_key: Mapped[str | None] = mapped_column(String(32))
    jira_attempts: Mapped[int] = mapped_column(Integer, default=0)
    jira_next_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    jira_error: Mapped[str | None] = mapped_column(Text)
    jira_status_pending: Mapped[str | None] = mapped_column(String(24))  # a status change not yet sent to Jira
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    taken_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    @property
    def key(self) -> str:
        return f"ESC-{self.id}"


class EscalationMessage(Base):
    __tablename__ = "escalation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    escalation_id: Mapped[int] = mapped_column(ForeignKey("escalations.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(16))  # user | support | system
    author_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    author_name: Mapped[str | None] = mapped_column(String(128))
    text: Mapped[str] = mapped_column(Text)
    internal: Mapped[bool] = mapped_column(Boolean, default=False)  # a support note the user never sees
    jira_comment_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    jira_synced: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)


class JiraSettings(Base):
    __tablename__ = "jira_settings"

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    base_url: Mapped[str] = mapped_column(String(256))
    email: Mapped[str] = mapped_column(String(256))
    api_token_enc: Mapped[str] = mapped_column(Text)
    project_key: Mapped[str] = mapped_column(String(32))
    issue_type: Mapped[str] = mapped_column(String(64), default="Task")
    webhook_secret_enc: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, onupdate=utc_now)


class DeliveryStatus(enum.StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"  # no webhook configured: the event is only available by polling


class Event(Base):
    """Outbox of events for integrations. `id` is the polling cursor; webhooks deliver the same rows."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_integration_id", "integration_id", "id"),
                      Index("ix_events_delivery", "delivery_status", "next_attempt_at"))

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id", ondelete="CASCADE"))
    project_public_id: Mapped[str] = mapped_column(String(8))
    type: Mapped[str] = mapped_column(String(48))
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    delivery_status: Mapped[str] = mapped_column(String(16), default=DeliveryStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class IndexJob(Base):
    """An indexing job started in the RAG for a project: the worker follows it and announces `docs.updated`."""

    __tablename__ = "index_jobs"

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | done | failed
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
