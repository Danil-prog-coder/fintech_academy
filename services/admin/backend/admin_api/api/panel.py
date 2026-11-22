"""API of the site for owners, admins and support (`/panel/api/*`): cookie session, role-gated.

A person registers a site account, then creates a project, joins one as an admin with the project code, or attaches
access given by an integration (a one-time link); the session remembers the chosen project.
Owner — everything; admin — documentation, users, questions without an answer, statistics, FAQ, tickets (read and
work); support — tickets only. Members themselves are registered by the integration (their ids are the
integrator's); the site edits statuses and sections of existing members.
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import Core
from ..errors import ApiError, bad_request, conflict, forbidden, not_found
from ..models import Escalation, JiraSettings, Member, Section
from ..rag_client import RagError, RagUnavailable
from ..security import new_token, verify_secret
from ..services import accounts, docs, escalations, projects, questions, stats
from ..services.accounts import SESSION_COOKIE, PanelUser, SiteSession
from ..services.jira import JiraError
from .deps import client_ip, get_core, get_db, managers, owner_only, panel_user, site_session, support_staff

router = APIRouter(prefix="/panel/api", tags=["panel"])
UPLOAD_MAX_BYTES = 50 * 1024 * 1024
UPLOAD_EXT = {".docx", ".pdf", ".md", ".markdown", ".txt"}


def _rag_errors(e: Exception) -> ApiError:
    if isinstance(e, RagUnavailable):
        return ApiError(503, "llm_unavailable", "Сервис базы знаний временно недоступен", retryable=True)
    if isinstance(e, RagError):
        return ApiError(e.status if e.status in (404, 409, 413, 415, 422) else 502, "kb_error", e.detail)
    return ApiError(500, "internal_error", "Внутренняя ошибка")


# ------------------------------------------------------------------ auth: site account
class CredentialsIn(BaseModel):
    login: str = Field(max_length=64)
    password: str = Field(max_length=128)


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=128)


class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class JoinIn(BaseModel):
    project_code: str = Field(max_length=64)


def _me(s: SiteSession) -> dict:
    """The signed-in account and, when a project is chosen, the project and the role in it."""
    out = {"login": s.user.login, "project": None, "role": None, "display_name": None, "external_id": None}
    if s.account is not None and s.project is not None:
        out.update(project={"id": s.project.public_id, "name": s.project.name}, role=s.account.member.role,
                   display_name=s.account.member.display_name, external_id=s.account.member.external_id)
    return out


def _set_cookie(response: Response, core: Core, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=core.settings.cookie_secure, samesite="lax",
                        max_age=core.settings.session_ttl_hours * 3600, path="/")


@router.post("/auth/register", status_code=201)
async def register(body: CredentialsIn, request: Request, response: Response, core: Core = Depends(get_core),
                   db: AsyncSession = Depends(get_db)) -> dict:
    token, s = await accounts.register(core, db, body.login, body.password, client_ip(request))
    _set_cookie(response, core, token)
    return _me(s)


@router.post("/auth/login")
async def login(body: CredentialsIn, request: Request, response: Response, core: Core = Depends(get_core),
                db: AsyncSession = Depends(get_db)) -> dict:
    token, s = await accounts.login(core, db, body.login, body.password, client_ip(request))
    _set_cookie(response, core, token)
    return _me(s)


@router.post("/auth/logout", status_code=204)
async def logout(response: Response, s: SiteSession = Depends(site_session), db: AsyncSession = Depends(get_db)) -> Response:
    await accounts.logout(db, s.session_hash)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/auth/invite")
async def invite(token: str = Query(min_length=10, max_length=128), db: AsyncSession = Depends(get_db)) -> dict:
    """What a link from an integration gives: project and status (shown before signing in)."""
    return await accounts.invite_info(db, token)


@router.post("/auth/claim")
async def claim(body: TokenIn, s: SiteSession = Depends(site_session), db: AsyncSession = Depends(get_db)) -> dict:
    """Attach the access from the link to the signed-in account and open that project."""
    return _me(await accounts.claim(db, s, body.token))


@router.get("/me")
async def me(s: SiteSession = Depends(site_session)) -> dict:
    return _me(s)


# ------------------------------------------------------------------ projects of the account
@router.get("/projects")
async def my_projects(s: SiteSession = Depends(site_session), db: AsyncSession = Depends(get_db)) -> dict:
    return {"projects": await accounts.my_projects(db, s)}


@router.post("/projects", status_code=201)
async def create_project(body: ProjectCreateIn, s: SiteSession = Depends(site_session), core: Core = Depends(get_core),
                         db: AsyncSession = Depends(get_db)) -> dict:
    """Create a project: the account becomes its owner. The project code is shown once (later — in «Настройки»)."""
    s, code = await accounts.create_project(core, db, s, body.name)
    return {**_me(s), "project_code": code}


@router.post("/projects/join")
async def join_project(body: JoinIn, request: Request, s: SiteSession = Depends(site_session),
                       core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> dict:
    """Join a project as an admin with its code."""
    return _me(await accounts.join_as_admin(core, db, s, body.project_code, client_ip(request)))


@router.post("/projects/{project_id}/select")
async def select_project(project_id: str, s: SiteSession = Depends(site_session), db: AsyncSession = Depends(get_db)) -> dict:
    return _me(await accounts.select_project(db, s, project_id))


# ------------------------------------------------------------------ project
@router.get("/project")
async def project(user: PanelUser = Depends(panel_user)) -> dict:
    p = user.project
    return {"id": p.public_id, "name": p.name, "created_at": p.created_at.isoformat(),
            "code_issued_at": p.code_issued_at.isoformat()}


@router.get("/project/code")
async def project_code(user: PanelUser = Depends(owner_only), core: Core = Depends(get_core)) -> dict:
    return {"code": core.box.decrypt(user.project.code_enc), "issued_at": user.project.code_issued_at.isoformat()}


@router.post("/project/code/rotate")
async def rotate(user: PanelUser = Depends(owner_only), core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> dict:
    p = await db.merge(user.project)
    return {"code": await projects.rotate_code(core, db, p)}


# ------------------------------------------------------------------ sections
class SectionIn(BaseModel):
    slug: str = Field(max_length=40)
    title: str = Field(min_length=1, max_length=64)


@router.get("/sections")
async def list_sections(user: PanelUser = Depends(managers), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.scalars(select(Section).where(Section.project_id == user.project.id).order_by(Section.id))).all()
    return {"sections": [{"slug": s.slug, "title": s.title} for s in rows]}


@router.post("/sections", status_code=201)
async def add_section(body: SectionIn, user: PanelUser = Depends(managers), db: AsyncSession = Depends(get_db)) -> dict:
    if not projects.SECTION_SLUG_RE.match(body.slug):
        raise bad_request("bad_section", "Код раздела: латиница в нижнем регистре, цифры, «-» и «_»")
    if body.slug in await projects.section_slugs(db, user.project):
        raise conflict("section_exists", "Такой раздел уже есть")
    db.add(Section(project_id=user.project.id, slug=body.slug, title=body.title.strip()))
    await db.commit()
    return {"slug": body.slug, "title": body.title}


@router.delete("/sections/{slug}", status_code=204)
async def delete_section(slug: str, user: PanelUser = Depends(managers), core: Core = Depends(get_core),
                         db: AsyncSession = Depends(get_db)) -> Response:
    if slug == projects.DEFAULT_SECTION[0]:
        raise bad_request("default_section", "Раздел «Общее» удалить нельзя")
    sec = await db.scalar(select(Section).where(Section.project_id == user.project.id, Section.slug == slug))
    if sec is None:
        raise not_found("section_not_found", "Раздел не найден")
    try:
        staged = (await core.rag.staged(user.project.rag_project_id)).get("files", [])
    except (RagError, RagUnavailable) as e:
        raise _rag_errors(e) from e
    if any(f.get("section") == slug for f in staged):
        raise conflict("section_not_empty", "В разделе есть документы — сначала удалите их")
    for m in (await db.scalars(select(Member).where(Member.project_id == user.project.id))).all():
        if m.allowed_sections and slug in m.allowed_sections:
            m.allowed_sections = [s for s in m.allowed_sections if s != slug]
    await db.delete(sec)
    await db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ documents
@router.get("/documents")
async def documents(user: PanelUser = Depends(managers), core: Core = Depends(get_core)) -> dict:
    pid = user.project.rag_project_id
    try:
        published = await core.rag.documents(pid)
        staged = await core.rag.staged(pid)
    except (RagError, RagUnavailable) as e:
        raise _rag_errors(e) from e
    return {"published": published, "files": staged.get("files", [])}


@router.post("/documents")
async def upload(files: list[UploadFile] = File(...), section: str = Form("general"),
                 mode: Literal["append", "replace"] = Form("append"), project_code: str | None = Form(None),
                 summary: str | None = Form(None, max_length=500),
                 user: PanelUser = Depends(managers), core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> dict:
    if section not in await projects.section_slugs(db, user.project):
        raise bad_request("unknown_section", "Нет такого раздела")
    if mode == "replace" and not await verify_secret(user.project.code_hash, (project_code or "").strip()):
        raise forbidden("project_code_required", "Замена раздела подтверждается кодом проекта")
    payload = []
    for f in files[:20]:
        name = re.sub(r"[\\/\x00-\x1f]", "_", f.filename or "file")[:120]
        if not any(name.lower().endswith(ext) for ext in UPLOAD_EXT):
            raise ApiError(415, "unsupported_format", "Поддерживаются .docx, .pdf, .md и .txt")
        content = await f.read(UPLOAD_MAX_BYTES + 1)
        if len(content) > UPLOAD_MAX_BYTES:
            raise ApiError(413, "file_too_large", "Файл больше 50 МБ")
        payload.append((name, content, f.content_type or "application/octet-stream"))
    try:
        res = await core.rag.upload(user.project.rag_project_id, section, mode, payload)
    except (RagError, RagUnavailable) as e:
        raise _rag_errors(e) from e
    await docs.track(db, user.project, res.get("job"), f"upload:{mode}",
                     summary or f"{'Заменён раздел' if mode == 'replace' else 'Добавлены документы'}: "
                                f"{', '.join(n for n, _, _ in payload)}")
    return res


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, user: PanelUser = Depends(managers), core: Core = Depends(get_core),
                          db: AsyncSession = Depends(get_db)) -> dict:
    try:
        res = await core.rag.delete_document(user.project.rag_project_id, doc_id)
    except (RagError, RagUnavailable) as e:
        raise _rag_errors(e) from e
    await docs.track(db, user.project, res.get("job"), "delete", f"Удалён документ: {', '.join(res.get('deleted', []))}")
    return res


@router.post("/reindex")
async def reindex(user: PanelUser = Depends(managers), core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> dict:
    try:
        job = await core.rag.reindex(user.project.rag_project_id)
    except (RagError, RagUnavailable) as e:
        raise _rag_errors(e) from e
    await docs.track(db, user.project, job, "reindex", "Переиндексация базы")
    return job


@router.get("/jobs")
async def jobs(user: PanelUser = Depends(managers), core: Core = Depends(get_core)) -> dict:
    try:
        return await core.rag.jobs(user.project.rag_project_id)
    except (RagError, RagUnavailable) as e:
        raise _rag_errors(e) from e


@router.post("/rollback")
async def rollback(user: PanelUser = Depends(managers), core: Core = Depends(get_core)) -> dict:
    try:
        return await core.rag.rollback(user.project.rag_project_id)
    except (RagError, RagUnavailable) as e:
        raise _rag_errors(e) from e


# ------------------------------------------------------------------ members
class MemberPatch(BaseModel):
    role: Literal["admin", "support", "user"] | None = None
    login: str | None = Field(default=None, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)
    allowed_sections: list[str] | None = None
    set_sections: bool = Field(default=False, description="true — применить allowed_sections (null = все разделы)")


@router.get("/members")
async def members(role: str | None = None, limit: int = Query(200, le=1000), offset: int = 0,
                  user: PanelUser = Depends(managers), db: AsyncSession = Depends(get_db)) -> dict:
    q = select(Member).where(Member.project_id == user.project.id)
    if role:
        q = q.where(Member.role == role)
    rows = (await db.scalars(q.order_by(Member.id).limit(limit).offset(offset))).all()
    return {"members": [projects.member_view(m) for m in rows]}


@router.patch("/members/{external_id}")
async def patch_member(external_id: str, body: MemberPatch, user: PanelUser = Depends(managers),
                       core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> dict:
    target = await projects.find_member(db, user.project, projects.check_external_id(external_id))
    if target is None:
        raise not_found("member_not_found", "Участник не найден")
    res = await projects.set_member(core, db, user.project, user.member.external_id, external_id,
                                    body.role or target.role, body.display_name, body.login,
                                    body.allowed_sections if body.set_sections else ...)
    out = {"member": projects.member_view(res.member)}
    if res.panel_setup_url:
        out["panel_setup_url"] = res.panel_setup_url
    return out


@router.delete("/members/{external_id}", status_code=204)
async def delete_member(external_id: str, user: PanelUser = Depends(managers), db: AsyncSession = Depends(get_db)) -> Response:
    await projects.remove_member(db, user.project, user.member.external_id, external_id)
    return Response(status_code=204)


@router.post("/members/{external_id}/password-reset")
async def member_password_reset(external_id: str, user: PanelUser = Depends(owner_only), core: Core = Depends(get_core),
                                db: AsyncSession = Depends(get_db)) -> dict:
    return {"panel_setup_url": await projects.reset_panel_password(core, db, user.project, user.member.external_id, external_id)}


# ------------------------------------------------------------------ questions without an answer
class AnswerIn(BaseModel):
    text: str = Field(min_length=3, max_length=20000)
    save_to_kb: bool = False
    section: str | None = Field(default=None, max_length=40)


@router.get("/questions")
async def list_questions(status: Literal["pending", "answered", "dismissed"] | None = "pending",
                         limit: int = Query(50, le=200), offset: int = 0,
                         user: PanelUser = Depends(managers), db: AsyncSession = Depends(get_db)) -> dict:
    rows, total = await questions.list_(db, user.project, status, limit, offset)
    return {"questions": [questions.view(q) for q in rows], "total": total}


@router.post("/questions/{qid}/answer")
async def answer_question(qid: int, body: AnswerIn, user: PanelUser = Depends(managers), core: Core = Depends(get_core),
                          db: AsyncSession = Depends(get_db)) -> dict:
    if body.section and body.section not in await projects.section_slugs(db, user.project):
        raise bad_request("unknown_section", "Нет такого раздела")
    member = await db.merge(user.member)
    return questions.view(await questions.answer(core, db, user.project, member, qid, body.text, body.save_to_kb, body.section))


@router.post("/questions/{qid}/dismiss")
async def dismiss_question(qid: int, user: PanelUser = Depends(managers), db: AsyncSession = Depends(get_db)) -> dict:
    return questions.view(await questions.dismiss(db, user.project, await db.merge(user.member), qid))


# ------------------------------------------------------------------ statistics and FAQ cache
@router.get("/stats")
async def project_stats(days: int = Query(7, ge=1, le=365), user: PanelUser = Depends(managers),
                        core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> dict:
    return await stats.summary(core, db, user.project, days)


@router.get("/faq")
async def faq(user: PanelUser = Depends(managers), core: Core = Depends(get_core)) -> dict:
    try:
        entries = await core.rag.faq_entries(user.project.rag_project_id)
    except (RagError, RagUnavailable) as e:
        raise _rag_errors(e) from e
    keep = ("id", "question", "paraphrases", "origin", "enabled", "status", "served", "likes", "dislikes", "updated_at")
    return {"entries": [{**{k: e.get(k) for k in keep}, "answer": (e.get("answer") or {}).get("text")} for e in entries]}


@router.post("/faq/recompute")
async def faq_recompute(user: PanelUser = Depends(managers), core: Core = Depends(get_core)) -> dict:
    try:
        return await core.rag.faq_recompute(user.project.rag_project_id)
    except (RagError, RagUnavailable) as e:
        raise _rag_errors(e) from e


@router.delete("/faq/{entry_id}", status_code=204)
async def faq_delete(entry_id: str, user: PanelUser = Depends(managers), core: Core = Depends(get_core)) -> Response:
    try:
        await core.rag.faq_delete(user.project.rag_project_id, entry_id)
    except (RagError, RagUnavailable) as e:
        raise _rag_errors(e) from e
    return Response(status_code=204)


# ------------------------------------------------------------------ support tickets
class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    internal: bool = False


class StatusIn(BaseModel):
    status: Literal["waiting", "in_progress", "waiting_customer", "resolved", "closed"]


class SaveKbIn(BaseModel):
    answer: str | None = Field(default=None, max_length=20000, description="по умолчанию — последние ответы поддержки")
    section: str | None = Field(default=None, max_length=40)


@router.get("/escalations")
async def list_escalations(status: str | None = "open", limit: int = Query(50, le=200), offset: int = 0,
                           user: PanelUser = Depends(support_staff), db: AsyncSession = Depends(get_db)) -> dict:
    rows = await escalations.list_for_panel(db, user.project, status, limit, offset)
    return {"escalations": [escalations.view(e, for_user=False) for e in rows]}


@router.get("/escalations/{key}")
async def get_escalation(key: str, user: PanelUser = Depends(support_staff), db: AsyncSession = Depends(get_db)) -> dict:
    e = await escalations.get(db, user.project, key)
    return escalations.view(e, await escalations.messages_of(db, e), for_user=False)


@router.post("/escalations/{key}/take")
async def take(key: str, user: PanelUser = Depends(support_staff), db: AsyncSession = Depends(get_db)) -> dict:
    return escalations.view(await escalations.take(db, user.project, await db.merge(user.member), key), for_user=False)


@router.post("/escalations/{key}/reply", status_code=201)
async def reply(key: str, body: ReplyIn, user: PanelUser = Depends(support_staff), db: AsyncSession = Depends(get_db)) -> dict:
    msg = await escalations.reply(db, user.project, await db.merge(user.member), key, body.text, body.internal)
    return {"id": msg.id, "created_at": msg.created_at.isoformat()}


@router.post("/escalations/{key}/status")
async def set_status(key: str, body: StatusIn, user: PanelUser = Depends(support_staff), db: AsyncSession = Depends(get_db)) -> dict:
    return escalations.view(await escalations.set_status(db, user.project, await db.merge(user.member), key, body.status),
                            for_user=False)


@router.post("/escalations/{key}/save-to-kb")
async def save_to_kb(key: str, body: SaveKbIn, user: PanelUser = Depends(support_staff), core: Core = Depends(get_core),
                     db: AsyncSession = Depends(get_db)) -> dict:
    e: Escalation = await escalations.get(db, user.project, key)
    answer = (body.answer or "").strip()
    if not answer:
        msgs = await escalations.messages_of(db, e)
        answer = "\n\n".join(m.text for m in msgs if m.author == "support" and not m.internal)
    if len(answer) < 3:
        raise bad_request("empty_answer", "Нет ответа поддержки, который можно сохранить")
    if body.section and body.section not in await projects.section_slugs(db, user.project):
        raise bad_request("unknown_section", "Нет такого раздела")
    try:
        res = await core.rag.knowledge(user.project.rag_project_id, e.question, answer,
                                       user.member.display_name or user.account.login, body.section)
    except (RagError, RagUnavailable) as err:
        raise _rag_errors(err) from err
    await docs.track(db, user.project, res.get("job"), "knowledge", f"Ответ поддержки сохранён в базу ({e.key})")
    return {"saved": True, "file": res.get("file")}


# ------------------------------------------------------------------ Jira (owner)
class JiraIn(BaseModel):
    base_url: str = Field(max_length=256)
    email: str = Field(max_length=256)
    api_token: str | None = Field(default=None, max_length=512, description="пусто — оставить прежний")
    project_key: str = Field(max_length=32)
    issue_type: str = Field(default="Task", max_length=64)
    enabled: bool = True


def _jira_view(core: Core, js: JiraSettings | None, project_public_id: str, secret: str | None = None) -> dict:
    if js is None:
        return {"configured": False}
    out = {"configured": True, "enabled": js.enabled, "base_url": js.base_url, "email": js.email,
           "project_key": js.project_key, "issue_type": js.issue_type,
           "webhook_url": f"{core.settings.api_public_url.rstrip('/')}/jira/webhook/{project_public_id}"}
    if secret:
        out["webhook_secret"] = secret
    return out


@router.get("/jira")
async def get_jira(user: PanelUser = Depends(owner_only), core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> dict:
    return _jira_view(core, await db.get(JiraSettings, user.project.id), user.project.public_id)


@router.put("/jira")
async def put_jira(body: JiraIn, user: PanelUser = Depends(owner_only), core: Core = Depends(get_core),
                   db: AsyncSession = Depends(get_db)) -> dict:
    if not body.base_url.startswith("https://"):
        raise bad_request("bad_jira_url", "Адрес Jira должен начинаться с https://")
    if not re.match(r"^[A-Z][A-Z0-9_]+$", body.project_key):
        raise bad_request("bad_jira_key", "Ключ проекта Jira: латиница в верхнем регистре, например SUP")
    js = await db.get(JiraSettings, user.project.id)
    secret = None
    if js is None:
        if not body.api_token:
            raise bad_request("api_token_required", "Нужен API-токен Jira")
        secret = new_token(24)
        js = JiraSettings(project_id=user.project.id, webhook_secret_enc=core.box.encrypt(secret), api_token_enc="")
        db.add(js)
    js.base_url, js.email, js.project_key, js.issue_type, js.enabled = (body.base_url.rstrip("/"), body.email,
                                                                        body.project_key, body.issue_type, body.enabled)
    if body.api_token:
        js.api_token_enc = core.box.encrypt(body.api_token)
    await db.commit()
    return _jira_view(core, js, user.project.public_id, secret)


@router.post("/jira/webhook-secret/rotate")
async def rotate_jira_secret(user: PanelUser = Depends(owner_only), core: Core = Depends(get_core),
                             db: AsyncSession = Depends(get_db)) -> dict:
    js = await db.get(JiraSettings, user.project.id)
    if js is None:
        raise not_found("jira_not_configured", "Jira не настроена")
    secret = new_token(24)
    js.webhook_secret_enc = core.box.encrypt(secret)
    await db.commit()
    return _jira_view(core, js, user.project.public_id, secret)


@router.post("/jira/check")
async def check_jira(user: PanelUser = Depends(owner_only), core: Core = Depends(get_core), db: AsyncSession = Depends(get_db)) -> dict:
    js = await db.get(JiraSettings, user.project.id)
    if js is None:
        raise not_found("jira_not_configured", "Jira не настроена")
    try:
        client = escalations.jira_client(core, js)
        return {"ok": True, "project": await client.check()}
    except JiraError as e:
        return {"ok": False, "error": str(e)}


