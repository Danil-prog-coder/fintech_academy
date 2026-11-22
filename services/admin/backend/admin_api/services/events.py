"""Outbox of integration events: one table, two ways to read it.

* Polling — `GET /v1/events?after=<cursor>`: the event id is the cursor, events are never lost for a client that
  keeps its cursor (at-least-once; `event_id` dedupes).
* Webhooks — the worker POSTs pending events to the integration's URL, signed `X-Platform-Signature:
  t=<unix>,v1=<hmac>`, with exponential back-off. Without a URL the event is marked `skipped` (still pollable).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import bad_request
from ..core.runtime import Core
from ..core.security import sign_webhook
from ..db.models import DeliveryStatus, Event, Integration
from ..db.session import utc_now

log = logging.getLogger(__name__)

EVENT_TYPES = (
    "question.answered",       # an admin answered a question the documentation did not cover
    "escalation.created",      # a support ticket was opened
    "escalation.message",      # support wrote to the user (never internal notes)
    "escalation.status_changed",
    "docs.updated",            # a new version of the project's knowledge base was published
)


def emit(session: AsyncSession, integration_id: int, project_public_id: str, type_: str, data: dict) -> Event:
    """Add an event in the caller's transaction: it is published together with the change it describes."""
    assert type_ in EVENT_TYPES, type_
    ev = Event(event_id=str(uuid.uuid4()), integration_id=integration_id, project_public_id=project_public_id, type=type_,
               data=data, delivery_status=DeliveryStatus.PENDING, next_attempt_at=utc_now())
    session.add(ev)
    return ev


def serialize(ev: Event) -> dict:
    return {"id": ev.id, "event_id": ev.event_id, "type": ev.type, "project_id": ev.project_public_id,
            "created_at": ev.created_at.isoformat(), "data": ev.data}


async def poll(session: AsyncSession, integration_id: int, after: int, limit: int) -> list[dict]:
    rows = (await session.scalars(select(Event).where(Event.integration_id == integration_id, Event.id > after)
                                  .order_by(Event.id).limit(limit))).all()
    return [serialize(e) for e in rows]


def check_webhook_url(url: str, allow_private: bool) -> str:
    """http(s) only, no credentials in the URL, and no private / loopback targets unless explicitly allowed (SSRF)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise bad_request("bad_webhook_url", "Адрес вебхука: http(s)://хост/путь без логина и пароля")
    if allow_private:
        return url
    if parts.scheme != "https":
        raise bad_request("bad_webhook_url", "Вебхук принимается только по https")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as e:
        raise bad_request("bad_webhook_url", "Хост вебхука не резолвится") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise bad_request("bad_webhook_url", "Вебхук не может вести во внутреннюю сеть")
    return url


def _backoff(attempt: int) -> timedelta:
    return timedelta(seconds=min(3600, 5 * 2 ** max(0, attempt - 1)))


async def deliver_pending(core: Core, session: AsyncSession, batch: int = 50) -> int:
    """One pass of the webhook worker. Rows are locked (SKIP LOCKED) so several workers never double-send."""
    now = utc_now()
    rows = (await session.scalars(
        select(Event).where(Event.delivery_status == DeliveryStatus.PENDING, Event.next_attempt_at <= now)
        .order_by(Event.id).limit(batch).with_for_update(skip_locked=True))).all()
    if not rows:
        return 0
    integrations = {i.id: i for i in (await session.scalars(
        select(Integration).where(Integration.id.in_({e.integration_id for e in rows})))).all()}
    sent = 0
    for ev in rows:
        integ = integrations.get(ev.integration_id)
        secret = core.box.decrypt(integ.webhook_secret_enc) if integ else None
        if not integ or not integ.webhook_url or not secret or integ.revoked_at:
            ev.delivery_status = DeliveryStatus.SKIPPED
            continue
        body = json.dumps(serialize(ev), ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json", "X-Platform-Event": ev.type, "X-Platform-Event-Id": ev.event_id,
                   "X-Platform-Signature": sign_webhook(secret, body)}
        ev.attempts += 1
        try:
            r = await core.http.post(integ.webhook_url, content=body, headers=headers)
            ok = 200 <= r.status_code < 300
            error = None if ok else f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001  (any network failure is a retry)
            ok, error = False, type(e).__name__
        if ok:
            ev.delivery_status, ev.delivered_at, ev.last_error = DeliveryStatus.DELIVERED, utc_now(), None
            sent += 1
        elif ev.attempts >= core.settings.webhook_max_attempts:
            ev.delivery_status, ev.last_error = DeliveryStatus.FAILED, error
            log.warning("webhook %s gave up after %s attempts: %s", ev.event_id, ev.attempts, error)
        else:
            ev.last_error, ev.next_attempt_at = error, utc_now() + _backoff(ev.attempts)
    await session.commit()
    return sent
