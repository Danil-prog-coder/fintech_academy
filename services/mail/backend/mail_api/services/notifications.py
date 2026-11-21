"""Platform events → notifications of our users. Polling (`GET /v1/events?after=`) with a cursor in our database:
the demo needs no public URL; a restart continues from the saved cursor (at-least-once, deduplicated by event_id)."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mail_api.core.errors import AppError
from mail_api.db.models import Notification, PlatformCursor, User
from mail_api.services.platform import PlatformClient, user_id_of

log = logging.getLogger(__name__)


def _render(ev: dict) -> tuple[str, str] | None:
    d = ev.get("data") or {}
    kind = ev.get("type")
    if kind == "question.answered":
        return f"Ответ на ваш вопрос: «{d.get('question', '')[:120]}»", d.get("answer", "")
    if kind == "escalation.message":
        return f"Поддержка ответила ({d.get('key')})", d.get("text", "")
    if kind == "escalation.status_changed":
        titles = {"in_progress": "в работе", "waiting_customer": "ждёт вашего ответа", "resolved": "решено", "closed": "закрыто"}
        status = titles.get(d.get("status"), d.get("status"))
        return f"Обращение {d.get('key')}: {status}", ""
    if kind == "escalation.created":
        return f"Создано обращение {d.get('key')}", "Специалист поддержки ответит здесь же."
    return None


async def apply_event(session: AsyncSession, ev: dict) -> int:
    """Store notifications for one event; returns how many users it reached."""
    rendered = _render(ev)
    if ev.get("type") == "docs.updated":
        return 0  # shown as a banner by the project list, not per user
    if rendered is None:
        return 0
    uid = user_id_of((ev.get("data") or {}).get("external_id", ""))
    if uid is None or await session.get(User, uid) is None:
        return 0
    title, text = rendered
    session.add(Notification(user_id=uid, event_id=ev["event_id"], type=ev["type"], project_id=ev.get("project_id", ""),
                             title=title[:300], text=text, data=ev.get("data") or {}))
    try:
        await session.flush()
    except IntegrityError:  # the same event again (at-least-once)
        await session.rollback()
        return 0
    return 1


async def poll_once(platform: PlatformClient, session: AsyncSession) -> int:
    cursor = await session.get(PlatformCursor, 1)
    if cursor is None:
        cursor = PlatformCursor(id=1, after=0)
        session.add(cursor)
        await session.flush()
    page = await platform.events(cursor.after)
    n = 0
    for ev in page.get("events", []):
        n += await apply_event(session, ev)
        cursor = await session.get(PlatformCursor, 1)  # survives a rollback of a duplicate
        cursor.after = max(cursor.after, int(ev["id"]))
    await session.commit()
    return n


async def run_poller(platform: PlatformClient, sessionmaker: async_sessionmaker, interval: float) -> None:
    while True:
        try:
            async with sessionmaker() as session:
                await poll_once(platform, session)
        except asyncio.CancelledError:
            raise
        except AppError as e:
            log.debug("platform events: %s", e.code)
        except Exception:
            log.exception("platform events poller failed")
        await asyncio.sleep(interval)


async def list_for(session: AsyncSession, user_id: int, unread_only: bool) -> list[Notification]:
    q = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    return list((await session.scalars(q.order_by(Notification.id.desc()).limit(100))).all())
