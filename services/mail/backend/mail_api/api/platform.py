"""Everything the mail demo does with the platform: projects and statuses, questions, support, notifications.

The demo owns its users (email + password); on the platform each of them is `mail-user-<id>`. The platform owns
projects and statuses and enforces who may change whom; this module only translates emails to our ids and back.
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mail_api.api.deps import current_user
from mail_api.core.errors import AppError
from mail_api.core.ratelimit import per_user
from mail_api.db.models import Notification, PlatformLink, User
from mail_api.db.session import get_session
from mail_api.schemas.common import ERROR_RESPONSES
from mail_api.services import notifications
from mail_api.services.platform import PlatformClient, external_id, user_id_of

router = APIRouter(tags=["platform"], responses=ERROR_RESPONSES)


def platform(request: Request) -> PlatformClient:
    return request.app.state.platform


async def current_project(session: AsyncSession, user: User, p: PlatformClient) -> str:
    """The chosen project; without a choice — the first project the platform lists for the user."""
    link = await session.get(PlatformLink, user.id)
    if link is not None and link.current_project_id:
        return link.current_project_id
    items = await p.projects_of(external_id(user.id))
    if not items:
        raise AppError("no_project", "Сначала создайте проект или попросите владельца добавить вас.", 409)
    await _set_current(session, user, items[0]["id"])
    return items[0]["id"]


async def _set_current(session: AsyncSession, user: User, project_id: str | None) -> None:
    link = await session.get(PlatformLink, user.id)
    if link is None:
        session.add(PlatformLink(user_id=user.id, current_project_id=project_id))
    else:
        link.current_project_id = project_id
    await session.commit()


async def _user_by_email(session: AsyncSession, email: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        raise AppError("user_not_registered", "Такого пользователя в почте нет: пусть сначала зарегистрируется.", 404)
    return user


# ------------------------------------------------------------------ projects
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    login: str = Field(min_length=3, max_length=64, description="логин для входа в панель администратора")


@router.get("/platform/projects")
async def projects(user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                   p: PlatformClient = Depends(platform)) -> dict:
    items = await p.projects_of(external_id(user.id))
    link = await session.get(PlatformLink, user.id)
    current = link.current_project_id if link else None
    if current and current not in {i["id"] for i in items}:
        current = None  # removed from the project on the platform
        await _set_current(session, user, None)
    if current is None and items:
        current = items[0]["id"]
        await _set_current(session, user, current)
    return {"projects": items, "current_project_id": current}


@router.post("/platform/projects", status_code=201)
async def create_project(body: ProjectCreate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                         p: PlatformClient = Depends(platform), _: None = per_user("projects", 10)) -> dict:
    res = await p.create_project(body.name, external_id(user.id), body.login, user.email)
    await _set_current(session, user, res["project"]["id"])
    return res  # project, project_code (shown once), owner_panel_setup_url


@router.post("/platform/projects/{project_id}/select")
async def select_project(project_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                         p: PlatformClient = Depends(platform)) -> dict:
    if project_id not in {i["id"] for i in await p.projects_of(external_id(user.id))}:
        raise AppError("not_a_member", "Вы не состоите в этом проекте.", 403)
    await _set_current(session, user, project_id)
    return {"current_project_id": project_id}


# ------------------------------------------------------------------ members (statuses are the platform's)
class MemberPut(BaseModel):
    email: EmailStr
    role: Literal["admin", "support", "user"]
    login: str | None = Field(default=None, max_length=64)
    allowed_sections: list[str] | None = None
    keep_sections: bool = True


@router.get("/platform/projects/{project_id}/members")
async def members(project_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                  p: PlatformClient = Depends(platform)) -> dict:
    items = await p.members(project_id)
    if external_id(user.id) not in {m["external_id"] for m in items}:
        raise AppError("not_a_member", "Вы не состоите в этом проекте.", 403)
    ids = [uid for m in items if (uid := user_id_of(m["external_id"])) is not None]
    emails = dict((await session.execute(select(User.id, User.email).where(User.id.in_(ids)))).all()) if ids else {}
    for m in items:
        uid = user_id_of(m["external_id"])
        m["email"] = emails.get(uid) if uid is not None else None
    return {"members": items, "sections": await p.sections(project_id)}


@router.put("/platform/projects/{project_id}/members")
async def put_member(project_id: str, body: MemberPut, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session), p: PlatformClient = Depends(platform)) -> dict:
    target = await _user_by_email(session, body.email)
    return await p.put_member(project_id, external_id(target.id), {
        "acting_external_id": external_id(user.id), "role": body.role, "display_name": target.email,
        "login": body.login, "allowed_sections": body.allowed_sections, "keep_sections": body.keep_sections})


@router.delete("/platform/projects/{project_id}/members/{email}", status_code=204)
async def delete_member(project_id: str, email: str, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session), p: PlatformClient = Depends(platform)) -> Response:
    target = await _user_by_email(session, email)
    await p.delete_member(project_id, external_id(target.id), external_id(user.id))
    return Response(status_code=204)


@router.post("/platform/projects/{project_id}/members/{email}/panel-link")
async def panel_link(project_id: str, email: str, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session), p: PlatformClient = Depends(platform)) -> dict:
    target = await _user_by_email(session, email)
    return await p.password_reset(project_id, external_id(target.id), external_id(user.id))


# ------------------------------------------------------------------ questions (chat page)
class ChatAsk(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class Feedback(BaseModel):
    request_id: str = Field(max_length=64)
    value: Literal[1, -1]


@router.post("/chat/ask")
async def chat_ask(body: ChatAsk, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                   p: PlatformClient = Depends(platform), _: None = per_user("ask", 30)) -> dict:
    pid = await current_project(session, user, p)
    return {"project_id": pid, **await p.ask(pid, external_id(user.id), body.message, channel="mail-chat")}


@router.post("/chat/reset", status_code=204)
async def chat_reset(user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                     p: PlatformClient = Depends(platform)) -> Response:
    await p.reset_dialog(await current_project(session, user, p), external_id(user.id))
    return Response(status_code=204)


@router.post("/chat/feedback")
async def chat_feedback(body: Feedback, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                        p: PlatformClient = Depends(platform)) -> dict:
    return await p.feedback(await current_project(session, user, p), external_id(user.id), body.request_id, body.value)


@router.get("/chat/popular")
async def chat_popular(user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                       p: PlatformClient = Depends(platform)) -> dict:
    return {"questions": await p.popular(await current_project(session, user, p))}


@router.get("/platform/images/{image_id:path}")
async def image(image_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                p: PlatformClient = Depends(platform)) -> Response:
    if not re.fullmatch(r"[\w./-]{1,200}", image_id) or ".." in image_id:
        raise AppError("not_found", "Картинка не найдена.", 404)
    r = await p.image(await current_project(session, user, p), image_id)
    return Response(r.content, media_type=r.headers.get("content-type"), headers={"Cache-Control": "private, max-age=3600"})


# ------------------------------------------------------------------ support
class SupportCreate(BaseModel):
    message: str | None = Field(default=None, max_length=4000)
    request_id: str | None = Field(default=None, max_length=64)


class SupportMessage(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


@router.post("/support", status_code=201)
async def support_create(body: SupportCreate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                         p: PlatformClient = Depends(platform)) -> dict:
    return await p.escalate(await current_project(session, user, p), external_id(user.id), body.message, body.request_id)


@router.get("/support")
async def support_list(user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                       p: PlatformClient = Depends(platform)) -> dict:
    return {"escalations": await p.escalations(await current_project(session, user, p), external_id(user.id))}


@router.get("/support/{key}")
async def support_get(key: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                      p: PlatformClient = Depends(platform)) -> dict:
    return await p.escalation(await current_project(session, user, p), external_id(user.id), key)


@router.post("/support/{key}/messages", status_code=201)
async def support_message(key: str, body: SupportMessage, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session), p: PlatformClient = Depends(platform)) -> dict:
    return await p.escalation_message(await current_project(session, user, p), external_id(user.id), key, body.text)


# ------------------------------------------------------------------ notifications
class ReadIn(BaseModel):
    ids: list[int] | None = None  # None — all


@router.get("/notifications")
async def list_notifications(unread: bool = False, user: User = Depends(current_user),
                             session: AsyncSession = Depends(get_session)) -> dict:
    rows = await notifications.list_for(session, user.id, unread)
    return {"notifications": [{"id": n.id, "type": n.type, "project_id": n.project_id, "title": n.title, "text": n.text,
                               "data": n.data, "read": n.read_at is not None, "created_at": n.created_at.isoformat()}
                              for n in rows]}


@router.post("/notifications/read", status_code=204)
async def read_notifications(body: ReadIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> Response:
    from datetime import UTC, datetime

    q = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if body.ids is not None:
        q = q.where(Notification.id.in_(body.ids))
    await session.execute(q.values(read_at=datetime.now(UTC)))
    await session.commit()
    return Response(status_code=204)
