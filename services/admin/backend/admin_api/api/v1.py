"""Open API for integrations: `/v1/*`, authenticated by `X-Api-Key`.

The integrator passes its own user ids (`external_id`) and statuses; the platform keeps projects, statuses,
answers, tickets and events. See docs/API.md for the full contract.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import Core
from ..db import sessionmaker
from ..errors import ApiError, bad_request, not_found
from ..models import Escalation, Integration, Member, Project, Section, Turn
from ..rag_client import RagError, RagUnavailable
from ..services import asking, escalations, events, integrations, projects, questions
from .deps import get_core, get_db, integration

router = APIRouter(prefix="/v1", tags=["integration API"])


# ------------------------------------------------------------------ models
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    owner_external_id: str = Field(min_length=1, max_length=128)
    owner_login: str = Field(min_length=3, max_length=64, description="логин владельца для входа на сайт")
    owner_display_name: str | None = Field(default=None, max_length=128)


class MemberPut(BaseModel):
    acting_external_id: str = Field(description="кто выполняет действие: владелец или админ проекта")
    role: Literal["admin", "support", "user"]
    display_name: str | None = Field(default=None, max_length=128)
    login: str | None = Field(default=None, max_length=64, description="нужен для admin и support: логин на сайте")
    allowed_sections: list[str] | None = Field(default=None, description="разделы для user/support; null — все")
    keep_sections: bool = Field(default=True, description="true — не трогать разделы, если allowed_sections не передан")


class Acting(BaseModel):
    acting_external_id: str


class ImageIn(BaseModel):
    mime: str = "image/png"
    data_base64: str


class AskIn(BaseModel):
    external_id: str
    message: str = Field(default="", max_length=4000)
    images: list[ImageIn] | None = None
    channel: str | None = Field(default=None, max_length=32, description="канал интегратора: mail, telegram, web…")
    stream: bool = Field(default=False, description="true — ответ потоком SSE (status / delta / reset / final)")
    now: datetime | None = Field(default=None, description="подмена текущего времени (демонстрация нерабочих часов)")


class FeedbackIn(BaseModel):
    external_id: str
    request_id: str
    value: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=2000)


class EscalationIn(BaseModel):
    external_id: str
    message: str | None = Field(default=None, max_length=4000, description="текст обращения; по умолчанию — последний вопрос")
    request_id: str | None = None


class MessageIn(BaseModel):
    external_id: str
    text: str = Field(min_length=1, max_length=8000)


class RatingIn(BaseModel):
    external_id: str
    value: Literal[1, -1]


class WebhookIn(BaseModel):
    url: str = Field(max_length=512)


# ------------------------------------------------------------------ integration
@router.get("/integration")
async def me(integ: Integration = Depends(integration)) -> dict:
    return {"slug": integ.slug, "name": integ.name, "key_prefix": integ.key_prefix, "webhook_url": integ.webhook_url}


@router.put("/integration/webhook")
async def set_webhook(body: WebhookIn, integ: Integration = Depends(integration), core: Core = Depends(get_core),
                      db: AsyncSession = Depends(get_db)) -> dict:
    secret = await integrations.set_webhook(core, db, integ, body.url)
    return {"url": integ.webhook_url, "secret": secret,
            "note": "Секрет показывается один раз. Подпись: X-Platform-Signature: t=<unix>,v1=<hmac_sha256(secret, '<t>.<body>')>"}


@router.delete("/integration/webhook", status_code=204)
async def delete_webhook(integ: Integration = Depends(integration), db: AsyncSession = Depends(get_db)) -> Response:
    await integrations.clear_webhook(db, integ)
    return Response(status_code=204)


@router.get("/events")
async def poll_events(after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                      integ: Integration = Depends(integration), db: AsyncSession = Depends(get_db)) -> dict:
    items = await events.poll(db, integ.id, after, limit)
    return {"events": items, "next_after": items[-1]["id"] if items else after}


# ------------------------------------------------------------------ projects
@router.post("/projects", status_code=201)
async def create_project(body: ProjectCreate, integ: Integration = Depends(integration), core: Core = Depends(get_core),
                         db: AsyncSession = Depends(get_db)) -> dict:
    project, code, link = await projects.create_project(core, db, integ, body.name, body.owner_external_id,
                                                        body.owner_login, body.owner_display_name)
    return {"project": projects.project_view(project, "owner"), "project_code": code, "owner_panel_setup_url": link,
            "note": "Код проекта показывается один раз: вместе с логином и паролем он нужен для входа на сайт."}


@router.get("/projects")
async def list_projects(external_id: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                        integ: Integration = Depends(integration), db: AsyncSession = Depends(get_db)) -> dict:
    rows = await projects.list_projects(db, integ, external_id, limit, offset)
    return {"projects": [projects.project_view(p, role) for p, role in rows]}


@router.get("/projects/{project_id}")
async def get_project(project_id: str, integ: Integration = Depends(integration), db: AsyncSession = Depends(get_db)) -> dict:
    return projects.project_view(await projects.get_project(db, integ, project_id))


@router.get("/projects/{project_id}/sections")
async def sections(project_id: str, integ: Integration = Depends(integration), db: AsyncSession = Depends(get_db)) -> dict:
    p = await projects.get_project(db, integ, project_id)
    rows = (await db.scalars(select(Section).where(Section.project_id == p.id).order_by(Section.id))).all()
    return {"sections": [{"slug": s.slug, "title": s.title} for s in rows]}


# ------------------------------------------------------------------ members and statuses
@router.get("/projects/{project_id}/members")
async def members(project_id: str, role: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                  integ: Integration = Depends(integration), db: AsyncSession = Depends(get_db)) -> dict:
    p = await projects.get_project(db, integ, project_id)
    q = select(Member).where(Member.project_id == p.id)
    if role:
        q = q.where(Member.role == role)
    rows = (await db.scalars(q.order_by(Member.id).limit(limit).offset(offset))).all()
    return {"members": [projects.member_view(m) for m in rows]}


@router.get("/projects/{project_id}/members/{external_id}")
async def member(project_id: str, external_id: str, integ: Integration = Depends(integration),
                 db: AsyncSession = Depends(get_db)) -> dict:
    p = await projects.get_project(db, integ, project_id)
    m = await projects.find_member(db, p, projects.check_external_id(external_id))
    if m is None:
        raise not_found("member_not_found", "Участник не найден")
    return projects.member_view(m)


@router.put("/projects/{project_id}/members/{external_id}")
async def put_member(project_id: str, external_id: str, body: MemberPut, integ: Integration = Depends(integration),
                     core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> dict:
    p = await projects.get_project(db, integ, project_id)
    sections_arg = ... if (body.allowed_sections is None and body.keep_sections) else body.allowed_sections
    res = await projects.set_member(core, db, p, body.acting_external_id, external_id, body.role, body.display_name,
                                    body.login, sections_arg)
    out = {"member": projects.member_view(res.member)}
    if res.panel_setup_url:
        out["panel_setup_url"] = res.panel_setup_url
    return out


@router.delete("/projects/{project_id}/members/{external_id}", status_code=204)
async def delete_member(project_id: str, external_id: str, acting_external_id: str,
                        integ: Integration = Depends(integration), db: AsyncSession = Depends(get_db)) -> Response:
    p = await projects.get_project(db, integ, project_id)
    await projects.remove_member(db, p, acting_external_id, external_id)
    return Response(status_code=204)


@router.post("/projects/{project_id}/members/{external_id}/panel-password-reset")
async def panel_password_reset(project_id: str, external_id: str, body: Acting, integ: Integration = Depends(integration),
                               core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> dict:
    p = await projects.get_project(db, integ, project_id)
    return {"panel_setup_url": await projects.reset_panel_password(core, db, p, body.acting_external_id, external_id)}


# ------------------------------------------------------------------ questions and answers
@router.post("/projects/{project_id}/ask", response_model=None)
async def ask(project_id: str, body: AskIn, integ: Integration = Depends(integration), core: Core = Depends(get_core),
              db: AsyncSession = Depends(get_db)) -> dict | StreamingResponse:
    p = await projects.get_project(db, integ, project_id)
    m = await projects.require_member(db, p, body.external_id)
    images = [i.model_dump() for i in body.images] if body.images else None
    if not body.stream:
        return await asking.ask(core, db, integ, p, m, body.message, images, body.channel, body.now)
    asking._check_input(body.message, images)  # fail with a normal JSON error before the stream starts

    project_pk, member_pk, integ_pk = p.id, m.id, integ.id

    async def gen():
        # a session of its own: the request-scoped one may be closed before the body is streamed
        async with sessionmaker()() as s2:
            p2, m2, i2 = await s2.get(Project, project_pk), await s2.get(Member, member_pk), await s2.get(Integration, integ_pk)
            async for ev in asking.ask_stream(core, s2, i2, p2, m2, body.message, images, body.channel, body.now):
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/projects/{project_id}/members/{external_id}/reset-dialog", status_code=204)
async def reset_dialog(project_id: str, external_id: str, integ: Integration = Depends(integration),
                       core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> Response:
    p = await projects.get_project(db, integ, project_id)
    m = await projects.require_member(db, p, external_id)
    try:
        await core.rag.reset_session(asking.session_id(integ, p, m.external_id), p.rag_project_id)
    except RagUnavailable as e:
        raise ApiError(503, "llm_unavailable", "Сервис ответов временно недоступен", retryable=True) from e
    return Response(status_code=204)


@router.post("/projects/{project_id}/feedback")
async def feedback(project_id: str, body: FeedbackIn, integ: Integration = Depends(integration),
                   core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> dict:
    p = await projects.get_project(db, integ, project_id)
    m = await projects.require_member(db, p, body.external_id)
    turn = await db.scalar(select(Turn).where(Turn.request_id == body.request_id, Turn.project_id == p.id,
                                              Turn.external_id == m.external_id))
    if turn is None:
        raise not_found("answer_not_found", "Ответ не найден")
    turn.rating = body.value
    out: dict = {"ok": True}
    if body.value < 0:
        q = await questions.add(db, p, m, m.external_id, turn.question, f"{turn.request_id}:dislike", "dislike")
        if q is not None:
            out["question_id"] = q.id
    await db.commit()
    try:
        await core.rag.feedback(turn.request_id, "up" if body.value > 0 else "down",
                                asking.session_id(integ, p, m.external_id), body.comment)
    except (RagError, RagUnavailable):
        out["note"] = "оценка сохранена, аналитика обновится позже"
    return out


@router.get("/projects/{project_id}/faq/popular")
async def popular(project_id: str, limit: int = Query(5, ge=1, le=20), integ: Integration = Depends(integration),
                  core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> dict:
    p = await projects.get_project(db, integ, project_id)
    try:
        return await core.rag.faq_popular(p.rag_project_id, limit)
    except (RagError, RagUnavailable):
        return {"questions": []}


@router.get("/projects/{project_id}/images/{image_id:path}")
async def image(project_id: str, image_id: str, crop: bool = False, integ: Integration = Depends(integration),
                core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> Response:
    p = await projects.get_project(db, integ, project_id)
    try:
        r = await core.rag.image(p.rag_project_id, image_id, crop)
    except RagError as e:
        raise not_found("image_not_found", "Картинка не найдена") from e
    except RagUnavailable as e:
        raise ApiError(503, "llm_unavailable", "Сервис ответов временно недоступен", retryable=True) from e
    return Response(r.content, media_type=r.headers.get("content-type", "application/octet-stream"),
                    headers={"Cache-Control": "private, max-age=3600"})


# ------------------------------------------------------------------ support tickets
@router.post("/projects/{project_id}/escalations", status_code=201)
async def create_escalation(project_id: str, body: EscalationIn, integ: Integration = Depends(integration),
                            core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> dict:
    p = await projects.get_project(db, integ, project_id)
    m = await projects.require_member(db, p, body.external_id)
    question = (body.message or "").strip()
    if not question:
        last = await db.scalar(select(Turn).where(Turn.project_id == p.id, Turn.external_id == m.external_id)
                               .order_by(Turn.id.desc()))
        question = last.question if last else ""
    if not question:
        raise bad_request("empty_message", "Опишите вопрос для поддержки")
    e = await escalations.create(core, db, p, m, question=question, reason="user_request", request_id=body.request_id)
    return escalations.view(e, await escalations.messages_of(db, e))


@router.get("/projects/{project_id}/escalations")
async def list_escalations(project_id: str, external_id: str, status: Literal["open", "all"] = "all",
                           integ: Integration = Depends(integration), db: AsyncSession = Depends(get_db)) -> dict:
    p = await projects.get_project(db, integ, project_id)
    m = await projects.require_member(db, p, external_id)
    q = select(Escalation).where(Escalation.project_id == p.id, Escalation.external_id == m.external_id)
    rows = (await db.scalars(q.order_by(Escalation.id.desc()).limit(50))).all()
    items = [escalations.view(e) for e in rows]
    if status == "open":
        items = [i for i in items if i["status"] not in ("resolved", "closed")]
    return {"escalations": items}


@router.get("/projects/{project_id}/escalations/{key}")
async def get_escalation(project_id: str, key: str, external_id: str, integ: Integration = Depends(integration),
                         db: AsyncSession = Depends(get_db)) -> dict:
    p = await projects.get_project(db, integ, project_id)
    m = await projects.require_member(db, p, external_id)
    e = await escalations.get(db, p, key)
    if e.external_id != m.external_id:
        raise not_found("escalation_not_found", "Обращение не найдено")
    return escalations.view(e, await escalations.messages_of(db, e))


@router.post("/projects/{project_id}/escalations/{key}/messages", status_code=201)
async def escalation_message(project_id: str, key: str, body: MessageIn, integ: Integration = Depends(integration),
                             db: AsyncSession = Depends(get_db)) -> dict:
    p = await projects.get_project(db, integ, project_id)
    m = await projects.require_member(db, p, body.external_id)
    msg = await escalations.user_message(db, p, m, key, body.text)
    return {"id": msg.id, "created_at": msg.created_at.isoformat()}


@router.post("/projects/{project_id}/escalations/{key}/rating")
async def escalation_rating(project_id: str, key: str, body: RatingIn, integ: Integration = Depends(integration),
                            db: AsyncSession = Depends(get_db)) -> dict:
    p = await projects.get_project(db, integ, project_id)
    m = await projects.require_member(db, p, body.external_id)
    await escalations.rate(db, p, m, key, body.value)
    return {"ok": True}
