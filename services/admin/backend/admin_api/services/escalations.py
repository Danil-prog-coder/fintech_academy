"""Support tickets (ТП) and their Jira mirror.

The platform's database is the source of truth; Jira is a mirror for the support team:
* a ticket is created at once; when the project has Jira configured it is queued (`jira_state=pending`) and the worker
  creates the issue — idempotently, by a label derived from the ticket id;
* messages of the user and replies from the site are queued as Jira comments (`jira_synced=false`);
* status changes made on the site are queued as Jira transitions (`jira_status_pending`);
* the Jira webhook brings comments and status changes made in Jira back: a support comment becomes a message to the
  user (`escalation.message` event), a final status closes the ticket.
The worker retries with back-off; after JIRA_MAX_ATTEMPTS a ticket is marked `failed` and stays usable from the site.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import ApiError, bad_request, conflict, forbidden, not_found
from ..core.runtime import Core
from ..db.models import (
    Escalation,
    EscalationMessage,
    EscalationStatus,
    JiraSettings,
    Member,
    PanelAccount,
    Project,
    Role,
    Turn,
)
from ..db.session import utc_now
from . import events
from .jira import JiraAmbiguous, JiraClient, JiraConfig, JiraError, JiraEvent

log = logging.getLogger(__name__)

REASONS = {"user_request": "пользователь попросил человека", "needs_human_action": "нужно действие человека",
           "no_answer_in_docs": "нет ответа в документации", "repeated_failure": "повторные неудачи",
           "user_frustration": "пользователь недоволен", "conflicting_sources": "источники противоречат"}
PRIORITIES = {"low": "Low", "normal": "Medium", "high": "High", "urgent": "Highest"}
TEXT_MAX = 8000


def key_to_id(key: str) -> int:
    if not key.startswith("ESC-") or not key[4:].isdigit():
        raise not_found("escalation_not_found", "Обращение не найдено")
    return int(key[4:])


def view(e: Escalation, messages: list[EscalationMessage] | None = None, *, for_user: bool = True) -> dict:
    out = {"key": e.key, "status": e.status, "priority": e.priority, "reason": e.reason, "summary": e.summary,
           "question": e.question, "external_id": e.external_id, "created_at": e.created_at.isoformat(),
           "taken_at": e.taken_at.isoformat() if e.taken_at else None,
           "closed_at": e.closed_at.isoformat() if e.closed_at else None, "user_rating": e.user_rating}
    if not for_user:
        out.update({"jira_key": e.jira_key, "jira_state": e.jira_state, "jira_error": e.jira_error,
                    "history": e.history, "request_id": e.request_id, "assignee_member_id": e.assignee_member_id})
    if messages is not None:
        out["messages"] = [{"id": m.id, "author": m.author, "author_name": m.author_name if not for_user or m.author != "support"
                            else (m.author_name or "Поддержка"), "text": m.text, "internal": m.internal,
                            "created_at": m.created_at.isoformat()}
                           for m in messages if not (for_user and m.internal)]
    return out


async def jira_settings(session: AsyncSession, project_id: int) -> JiraSettings | None:
    js = await session.get(JiraSettings, project_id)
    return js if js is not None and js.enabled else None


def jira_client(core: Core, js: JiraSettings) -> JiraClient:
    cfg = JiraConfig(js.base_url, js.email, core.box.decrypt(js.api_token_enc) or "", js.project_key, js.issue_type)
    if core.jira_factory is not None:
        return core.jira_factory(cfg)
    return JiraClient(cfg, core.http, core.settings.jira_timeout_s)


async def get(session: AsyncSession, project: Project, key: str) -> Escalation:
    e = await session.get(Escalation, key_to_id(key))
    if e is None or e.project_id != project.id:
        raise not_found("escalation_not_found", "Обращение не найдено")
    return e


async def messages_of(session: AsyncSession, e: Escalation) -> list[EscalationMessage]:
    return list((await session.scalars(select(EscalationMessage).where(EscalationMessage.escalation_id == e.id)
                                       .order_by(EscalationMessage.id))).all())


async def open_for(session: AsyncSession, project: Project, external_id: str) -> Escalation | None:
    return await session.scalar(select(Escalation).where(
        Escalation.project_id == project.id, Escalation.external_id == external_id,
        Escalation.status.in_([s.value for s in EscalationStatus if s.is_open])).order_by(Escalation.id.desc()))


async def history_of(session: AsyncSession, project: Project, external_id: str, limit: int = 6) -> list[dict]:
    rows = (await session.scalars(select(Turn).where(Turn.project_id == project.id, Turn.external_id == external_id)
                                  .order_by(Turn.id.desc()).limit(limit))).all()
    out: list[dict] = []
    for t in reversed(rows):
        out.append({"role": "user", "text": t.question})
        if t.answer:
            out.append({"role": "assistant", "text": t.answer})
    return out


async def create(core: Core, session: AsyncSession, project: Project, member: Member, *, question: str, summary: str = "",
                 reason: str = "user_request", urgency: str = "normal", history: list | None = None,
                 request_id: str | None = None, commit: bool = True) -> Escalation:
    """Open a ticket. One open ticket per person: a second request returns the open one (idempotent)."""
    existing = await open_for(session, project, member.external_id)
    if existing is not None:
        return existing
    question = (question or "").strip()[:TEXT_MAX] or "(без текста)"
    js = await jira_settings(session, project.id)
    e = Escalation(project_id=project.id, member_id=member.id, external_id=member.external_id,
                   reason=reason if reason in REASONS else "user_request", priority=PRIORITIES.get(urgency, "Medium"),
                   summary=(summary or question)[:2000], question=question,
                   history=history if history is not None else await history_of(session, project, member.external_id),
                   request_id=request_id, jira_state="pending" if js else "none", jira_next_at=utc_now() if js else None)
    session.add(e)
    await session.flush()
    session.add(EscalationMessage(escalation_id=e.id, author="user", author_member_id=member.id, text=question,
                                  jira_synced=True))  # the question is in the issue description
    integration_id = await _integration_id(session, project)
    events.emit(session, integration_id, project.public_id, "escalation.created",
                {"key": e.key, "external_id": e.external_id, "status": e.status, "reason": e.reason})
    if commit:
        await session.commit()
    return e


async def _integration_id(session: AsyncSession, project: Project) -> int:
    return project.integration_id


# ------------------------------------------------------------------ the user's side (API)
async def user_message(session: AsyncSession, project: Project, member: Member, key: str, text: str) -> EscalationMessage:
    e = await get(session, project, key)
    if e.external_id != member.external_id:
        raise not_found("escalation_not_found", "Обращение не найдено")
    if not EscalationStatus(e.status).is_open:
        raise conflict("escalation_closed", "Обращение закрыто — откройте новое")
    text = (text or "").strip()
    if not text:
        raise bad_request("empty_text", "Пустое сообщение")
    msg = EscalationMessage(escalation_id=e.id, author="user", author_member_id=member.id, text=text[:TEXT_MAX],
                            jira_synced=e.jira_state == "none")
    session.add(msg)
    if e.status == EscalationStatus.WAITING_CUSTOMER:
        e.status = EscalationStatus.IN_PROGRESS
    await session.commit()
    return msg


async def rate(session: AsyncSession, project: Project, member: Member, key: str, value: int) -> None:
    e = await get(session, project, key)
    if e.external_id != member.external_id:
        raise not_found("escalation_not_found", "Обращение не найдено")
    if EscalationStatus(e.status).is_open:
        raise conflict("escalation_open", "Оценить можно после закрытия обращения")
    e.user_rating = 1 if value > 0 else -1
    await session.commit()


# ------------------------------------------------------------------ the support side (site)
def _require_support(member: Member) -> None:
    if Role(member.role) not in (Role.OWNER, Role.ADMIN, Role.SUPPORT):
        raise forbidden()


async def _set_status(session: AsyncSession, project: Project, e: Escalation, status: EscalationStatus,
                      *, from_jira: bool = False) -> None:
    if e.status == status:
        return
    e.status = status
    now = utc_now()
    if status in (EscalationStatus.RESOLVED, EscalationStatus.CLOSED):
        e.closed_at = now
    elif status is EscalationStatus.IN_PROGRESS and e.taken_at is None:
        e.taken_at = now
    if not from_jira and e.jira_state != "none":
        e.jira_status_pending = status.value
    events.emit(session, project.integration_id, project.public_id, "escalation.status_changed",
                {"key": e.key, "external_id": e.external_id, "status": e.status})


async def take(session: AsyncSession, project: Project, actor: Member, key: str) -> Escalation:
    _require_support(actor)
    e = await get(session, project, key)
    if not EscalationStatus(e.status).is_open:
        raise conflict("escalation_closed", "Обращение уже закрыто")
    if e.assignee_member_id not in (None, actor.id):
        raise conflict("already_taken", "Обращение уже взял другой специалист")
    e.assignee_member_id = actor.id
    await _set_status(session, project, e, EscalationStatus.IN_PROGRESS)
    await session.commit()
    return e


async def reply(session: AsyncSession, project: Project, actor: Member, key: str, text: str, internal: bool) -> EscalationMessage:
    _require_support(actor)
    e = await get(session, project, key)
    if not EscalationStatus(e.status).is_open:
        raise conflict("escalation_closed", "Обращение закрыто")
    text = (text or "").strip()
    if not text:
        raise bad_request("empty_text", "Пустое сообщение")
    login = await session.scalar(select(PanelAccount.login).where(PanelAccount.member_id == actor.id))
    msg = EscalationMessage(escalation_id=e.id, author="support", author_member_id=actor.id,
                            author_name=actor.display_name or login,
                            text=text[:TEXT_MAX], internal=internal, jira_synced=e.jira_state == "none")
    session.add(msg)
    if e.assignee_member_id is None:
        e.assignee_member_id = actor.id
    if e.status == EscalationStatus.WAITING:
        await _set_status(session, project, e, EscalationStatus.IN_PROGRESS)
    await session.flush()
    if not internal:
        events.emit(session, project.integration_id, project.public_id, "escalation.message",
                    {"key": e.key, "external_id": e.external_id, "message_id": msg.id, "text": msg.text,
                     "author": "support", "author_name": msg.author_name or "Поддержка"})
    await session.commit()
    return msg


async def set_status(session: AsyncSession, project: Project, actor: Member, key: str, status: str) -> Escalation:
    _require_support(actor)
    try:
        new = EscalationStatus(status)
    except ValueError as e:
        raise bad_request("bad_status", "Статус: waiting, in_progress, waiting_customer, resolved, closed") from e
    esc = await get(session, project, key)
    await _set_status(session, project, esc, new)
    await session.commit()
    return esc


async def list_for_panel(session: AsyncSession, project: Project, status: str | None, limit: int, offset: int) -> list[Escalation]:
    q = select(Escalation).where(Escalation.project_id == project.id)
    if status == "open":
        q = q.where(Escalation.status.in_([s.value for s in EscalationStatus if s.is_open]))
    elif status:
        q = q.where(Escalation.status == status)
    return list((await session.scalars(q.order_by(Escalation.id.desc()).limit(limit).offset(offset))).all())


# ------------------------------------------------------------------ Jira worker and webhook
async def _jira_create(core: Core, session: AsyncSession, e: Escalation, js: JiraSettings, project: Project) -> None:
    client = jira_client(core, js)
    history = "\n".join(f"{'Пользователь' if h.get('role') == 'user' else 'Бот'}: {h.get('text', '')}" for h in e.history or [])
    description = (f"Проект: {project.name} ({project.public_id})\nЗаявитель (id в системе интегратора): {e.external_id}\n"
                   f"Причина: {REASONS.get(e.reason, e.reason)}\n\nВопрос:\n{e.question}\n\nРезюме:\n{e.summary}\n\n"
                   f"История диалога:\n{history or '—'}\n\nОбращение платформы: {e.key}")
    e.jira_key = await client.create_issue(f"[{project.name}] {e.summary[:200]}", description,
                                           ["platform", f"project-{project.public_id}"], e.priority, f"{project.public_id}-{e.key}")
    e.jira_state, e.jira_error, e.jira_next_at = "created", None, None


async def _jira_sync_ticket(core: Core, session: AsyncSession, e: Escalation, js: JiraSettings) -> None:
    client = jira_client(core, js)
    pending = (await session.scalars(select(EscalationMessage).where(EscalationMessage.escalation_id == e.id,
                                                                     EscalationMessage.jira_synced.is_(False))
                                     .order_by(EscalationMessage.id))).all()
    for m in pending:
        prefix = "//" if m.internal else ("[Пользователь]" if m.author == "user" else "[Поддержка]")
        cid = await client.add_comment(e.jira_key, f"{prefix} {m.text}")
        m.jira_synced, m.jira_comment_id = True, cid
    if e.jira_status_pending:
        await client.transition(e.jira_key, e.jira_status_pending)
        e.jira_status_pending = None


async def jira_pass(core: Core, session: AsyncSession, batch: int = 20) -> int:
    """One pass of the Jira worker: create pending issues, push queued comments and status changes."""
    now = utc_now()
    unsynced = select(EscalationMessage.escalation_id).where(EscalationMessage.jira_synced.is_(False))
    rows = (await session.scalars(select(Escalation).where(
        or_(Escalation.jira_state == "pending",
            (Escalation.jira_state == "created") & (Escalation.jira_status_pending.is_not(None) | Escalation.id.in_(unsynced))),
        or_(Escalation.jira_next_at.is_(None), Escalation.jira_next_at <= now))
        .order_by(Escalation.id).limit(batch).with_for_update(skip_locked=True))).all()
    done = 0
    for e in rows:
        project = await session.get(Project, e.project_id)
        js = await jira_settings(session, e.project_id)
        if js is None or project is None:
            e.jira_state = "none" if e.jira_state == "pending" else e.jira_state
            e.jira_status_pending = None
            continue
        try:
            if e.jira_state == "pending":
                await _jira_create(core, session, e, js, project)
            await _jira_sync_ticket(core, session, e, js)
            e.jira_attempts, e.jira_error = 0, None
            done += 1
        except (JiraError, JiraAmbiguous) as err:
            e.jira_attempts += 1
            e.jira_error = str(err)[:500]
            if e.jira_attempts >= core.settings.jira_max_attempts and e.jira_state == "pending":
                e.jira_state = "failed"
                log.warning("jira: giving up on %s: %s", e.key, err)
            else:
                e.jira_next_at = utc_now() + timedelta(seconds=min(1800, 10 * 2 ** e.jira_attempts))
    await session.commit()
    return done


async def on_jira_event(session: AsyncSession, project: Project, ev: JiraEvent) -> bool:
    e = await session.scalar(select(Escalation).where(Escalation.project_id == project.id, Escalation.jira_key == ev.issue_key))
    if e is None:
        return False
    if ev.kind == "comment" and ev.comment_text:
        if not EscalationStatus(e.status).is_open:
            return False
        msg = EscalationMessage(escalation_id=e.id, author="support", author_name=ev.comment_author or "Поддержка",
                                text=ev.comment_text[:TEXT_MAX], jira_comment_id=ev.comment_id, jira_synced=True)
        session.add(msg)
        try:
            await session.flush()
        except IntegrityError:  # the same Jira comment delivered twice
            await session.rollback()
            return False
        if e.status == EscalationStatus.WAITING:
            await _set_status(session, project, e, EscalationStatus.IN_PROGRESS, from_jira=True)
        events.emit(session, project.integration_id, project.public_id, "escalation.message",
                    {"key": e.key, "external_id": e.external_id, "message_id": msg.id, "text": msg.text,
                     "author": "support", "author_name": msg.author_name})
    elif ev.kind == "assigned" and e.status == EscalationStatus.WAITING:
        await _set_status(session, project, e, EscalationStatus.IN_PROGRESS, from_jira=True)
    elif ev.kind == "closed":
        await _set_status(session, project, e, EscalationStatus.RESOLVED, from_jira=True)
    else:
        return False
    await session.commit()
    return True


def ensure_open_status(e: Escalation) -> None:
    if not EscalationStatus(e.status).is_open:
        raise ApiError(409, "escalation_closed", "Обращение закрыто")
