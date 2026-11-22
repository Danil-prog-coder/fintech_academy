"""A question from an integration → the RAG service → the answer, with the platform's side effects.

The platform decides what the RAG may see (the member's sections) and what follows from the answer:
* `escalate` (the user asked for a human, or the agent decided so) → a support ticket is opened at once;
* `offer_operator` because the documentation had no answer → the question goes to the owner and admins;
  technical failures (model unavailable, time limit) do not — they are not documentation gaps;
* every turn is journaled for statistics and ratings.
The RAG's internal fields (token usage, trace, debug) never leave the platform.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import ApiError, bad_request
from ..core.runtime import Core
from ..core.security import sha256
from ..db.models import Integration, Member, Project, Turn
from . import escalations, questions
from .projects import visible_sections
from .rag import RagError, RagUnavailable

log = logging.getLogger(__name__)

PUBLIC_FIELDS = ("request_id", "action", "text", "formatted_text", "sources", "image_ids", "image_meta", "confidence",
                 "confidence_level", "reason", "buttons", "cache_hit", "latency_ms", "first_token_ms", "support")
NOT_A_DOC_GAP = {"llm_unavailable", "agent_limit", "internal_error", "citation_check_failed"}
MESSAGE_MAX = 4000
MAX_IMAGES = 3
IMAGE_MAX_B64 = 7_000_000  # ~5 MB of image data
IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def session_id(integ: Integration, project: Project, external_id: str) -> str:
    """The RAG keeps dialog memory per session; the integrator's raw id never reaches it."""
    return f"{integ.slug}:{project.public_id}:{sha256(external_id)[:24]}"


def _check_input(message: str, images: list[dict] | None, attachments: list[dict] | None = None) -> None:
    if len(message or "") > MESSAGE_MAX:
        raise bad_request("message_too_long", f"Сообщение длиннее {MESSAGE_MAX} символов")
    if not (message or "").strip() and not images and not attachments:
        raise bad_request("empty_message", "Пустой вопрос")
    for im in images or []:
        if im.get("mime") not in IMAGE_MIMES or len(im.get("data_base64") or "") > IMAGE_MAX_B64:
            raise bad_request("bad_image", "Картинка: png, jpeg, webp или gif до 5 МБ")
    if len(images or []) > MAX_IMAGES:
        raise bad_request("too_many_images", f"Не больше {MAX_IMAGES} картинок")
    if attachments and len(images or []) + len(attachments) > 3:
        raise bad_request("bad_attachment", "Не больше трёх файлов")


def _payload(integ: Integration, project: Project, member: Member, message: str, images: list[dict] | None,
             now: datetime | None, attachments: list[dict] | None) -> dict:
    payload = {"session_id": session_id(integ, project, member.external_id), "project_id": project.rag_project_id,
               "message": message or "", "images": images or None, "now": now.isoformat() if now else None,
               "allowed_sections": visible_sections(member)}
    if attachments:
        payload["attachments"] = attachments
    return payload


async def _finalize(core: Core, session: AsyncSession, project: Project, member: Member, message: str, raw: dict,
                    channel: str | None) -> dict:
    out = {k: raw[k] for k in PUBLIC_FIELDS if k in raw}
    base = core.settings.api_public_url.rstrip("/")
    out["images"] = [{"id": i, "url": f"{base}/v1/projects/{project.public_id}/images/{quote(i)}"}
                     for i in raw.get("image_ids") or []]
    for src in out.get("sources") or []:
        for k in ("chunk_id", "source_id", "score_debug"):
            src.pop(k, None)
    action, reason = raw.get("action") or "offer_operator", raw.get("reason")
    session.add(Turn(request_id=raw.get("request_id") or "", project_id=project.id, member_id=member.id,
                     external_id=member.external_id, channel=(channel or "")[:32] or None, question=message[:4000],
                     answer=(raw.get("text") or "")[:8000], action=action, reason=(reason or "")[:64] or None,
                     confidence=raw.get("confidence"), cache_hit=bool(raw.get("cache_hit")), latency_ms=raw.get("latency_ms")))
    if action == "escalate":
        e = await escalations.create(core, session, project, member, question=message, summary=raw.get("summary") or "",
                                     reason=reason or "user_request", urgency=raw.get("urgency") or "normal",
                                     history=raw.get("history"), request_id=raw.get("request_id"), commit=False)
        out["escalation"] = {"key": e.key, "status": e.status}
    elif action == "offer_operator" and reason not in NOT_A_DOC_GAP and message.strip():
        q = await questions.add(session, project, member, member.external_id, message, raw.get("request_id"), "no_answer")
        if q is not None:
            out["question_id"] = q.id
    await session.commit()
    return out


async def ask(core: Core, session: AsyncSession, integ: Integration, project: Project, member: Member, message: str,
              images: list[dict] | None, channel: str | None, now: datetime | None = None, *,
              attachments: list[dict] | None = None) -> dict:
    _check_input(message, images, attachments)
    try:
        raw = await core.rag.ask_sync(_payload(integ, project, member, message, images, now, attachments))
    except RagUnavailable as e:
        raise ApiError(503, "llm_unavailable", "Сервис ответов временно недоступен", retryable=True) from e
    except RagError as e:
        if attachments and e.status == 422:
            raise ApiError(422, "bad_attachment", e.detail) from e
        raise ApiError(502, "llm_error", "Сервис ответов отклонил запрос") from e
    return await _finalize(core, session, project, member, message, raw, channel)


async def ask_stream(core: Core, session: AsyncSession, integ: Integration, project: Project, member: Member,
                     message: str, images: list[dict] | None, channel: str | None,
                     now: datetime | None = None, *, attachments: list[dict] | None = None) -> AsyncIterator[dict]:
    """Events: status / delta / reset as the RAG sends them, then one `final` (the same object as the sync answer)."""
    _check_input(message, images, attachments)
    final = None
    try:
        async for ev in core.rag.ask_stream(_payload(integ, project, member, message, images, now, attachments)):
            if ev.get("type") == "final":
                final = ev
                break
            if ev.get("type") in ("status", "delta", "reset"):
                yield {k: v for k, v in ev.items() if k in ("type", "text")}
    except (RagUnavailable, RagError) as e:
        if attachments and isinstance(e, RagError) and e.status == 422:
            yield {"type": "error", "code": "bad_attachment", "message": e.detail, "retryable": False}
            return
        log.warning("ask stream failed: %s", e)
        yield {"type": "error", "code": "llm_unavailable", "message": "Сервис ответов временно недоступен", "retryable": True}
        return
    if final is None:
        yield {"type": "error", "code": "llm_unavailable", "message": "Ответ прервался", "retryable": True}
        return
    yield {"type": "final", **await _finalize(core, session, project, member, message, final, channel)}
