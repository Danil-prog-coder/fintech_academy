"""Projects, members and their statuses, panel accounts.

The integrator owns identity: it passes its own user ids (`external_id`) and the platform stores them with a status
(owner / admin / support / user). Rules (who may change whom) are enforced here, not trusted to the integrator:

* the owner is fixed at creation; nobody can become or stop being the owner;
* the owner assigns admin / support / user to anyone and removes anyone except himself;
* an admin manages only users: adds them, restricts their sections, removes them;
* nobody changes his own status.

owner / admin / support get a panel account (login + password + project code). The password is never sent through
the API: the response carries a one-time link where the person sets it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import Core
from ..db import utc_now
from ..errors import ApiError, bad_request, conflict, forbidden, not_found
from ..models import Integration, Member, PanelAccount, PanelSession, Project, Role, Section, SetupToken
from ..security import (
    LOGIN_RE,
    PUBLIC_ID_RE,
    hash_secret,
    new_project_code,
    new_public_id,
    new_token,
    normalize_login,
    sha256,
)

NAME_MAX = 64
EXTERNAL_ID_RE = re.compile(r"^[\w.@:+-]{1,128}$")
SECTION_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
DEFAULT_SECTION = ("general", "Общее")


@dataclass
class MemberResult:
    member: Member
    panel_setup_url: str | None = None


def check_external_id(external_id: str) -> str:
    external_id = (external_id or "").strip()
    if not EXTERNAL_ID_RE.match(external_id):
        raise bad_request("bad_external_id", "external_id: 1–128 символов, буквы, цифры и . _ @ : + -")
    return external_id


def check_login(login: str | None) -> str:
    login = normalize_login(login or "")
    if not LOGIN_RE.match(login):
        raise bad_request("bad_login", "Логин: 3–64 символа, латиница в нижнем регистре, цифры и . _ @ -")
    return login


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name or len(name) > NAME_MAX:
        raise bad_request("bad_project_name", f"Название проекта: от 1 до {NAME_MAX} символов")
    return name


# ------------------------------------------------------------------ lookups
async def get_project(session: AsyncSession, integ: Integration, public_id: str) -> Project:
    if not PUBLIC_ID_RE.match(public_id or ""):
        raise not_found("project_not_found", "Проект не найден")
    project = await session.scalar(select(Project).where(Project.public_id == public_id,
                                                         Project.integration_id == integ.id))
    if project is None:  # another integration's project is indistinguishable from a missing one
        raise not_found("project_not_found", "Проект не найден")
    return project


async def find_member(session: AsyncSession, project: Project, external_id: str) -> Member | None:
    return await session.scalar(select(Member).where(Member.project_id == project.id, Member.external_id == external_id))


async def require_member(session: AsyncSession, project: Project, external_id: str) -> Member:
    member = await find_member(session, project, check_external_id(external_id))
    if member is None:
        raise forbidden("not_a_member", "Пользователь не состоит в проекте")
    return member


async def section_slugs(session: AsyncSession, project: Project) -> set[str]:
    return set((await session.scalars(select(Section.slug).where(Section.project_id == project.id))).all())


def visible_sections(member: Member) -> list[str] | None:
    """What the RAG may search for this member: None — everything (managers always see everything)."""
    if Role(member.role).is_manager:
        return None
    return list(member.allowed_sections) if member.allowed_sections is not None else None


# ------------------------------------------------------------------ setup links
async def _setup_link(core: Core, session: AsyncSession, account: PanelAccount) -> str:
    """A fresh one-time link; earlier unused links of the account stop working."""
    await session.execute(delete(SetupToken).where(SetupToken.account_id == account.id, SetupToken.used_at.is_(None)))
    token = new_token(32)
    session.add(SetupToken(token_hash=sha256(token), account_id=account.id,
                           expires_at=utc_now() + timedelta(hours=core.settings.setup_link_ttl_hours)))
    return f"{core.settings.panel_public_url.rstrip('/')}/setup?token={token}"


async def _ensure_account(core: Core, session: AsyncSession, project: Project, member: Member,
                          login: str | None) -> str | None:
    """Panel account for owner / admin / support. Returns a setup link when the account is new."""
    if member.account is not None:
        if login and normalize_login(login) != member.account.login and member.account.password_hash is None:
            member.account.login = await _free_login(session, project, check_login(login), member.account.id)
        return None
    if not login:
        raise bad_request("login_required", "Для статусов owner, admin и support нужен login — им входят на сайт")
    account = PanelAccount(project_id=project.id, login=await _free_login(session, project, check_login(login)))
    member.account = account
    await session.flush()
    return await _setup_link(core, session, account)


async def _free_login(session: AsyncSession, project: Project, login: str, own_id: int | None = None) -> str:
    taken = await session.scalar(select(PanelAccount.id).where(PanelAccount.project_id == project.id,
                                                               PanelAccount.login == login))
    if taken is not None and taken != own_id:
        raise conflict("login_taken", "Такой логин в проекте уже занят")
    return login


# ------------------------------------------------------------------ projects
async def create_project(core: Core, session: AsyncSession, integ: Integration, name: str, owner_external_id: str,
                         owner_login: str, owner_display_name: str | None = None) -> tuple[Project, str, str]:
    """→ (project, project code — shown once, owner's password setup link)."""
    name = _clean_name(name)
    owner_external_id = check_external_id(owner_external_id)
    owner_login = check_login(owner_login)
    for _ in range(5):
        public_id = new_public_id()
        if await session.scalar(select(Project.id).where(Project.public_id == public_id)) is None:
            break
    else:  # 2^32 ids: practically unreachable
        raise ApiError(500, "id_allocation_failed", "Не удалось выделить идентификатор проекта", retryable=True)
    code = new_project_code(public_id)
    project = Project(public_id=public_id, integration_id=integ.id, name=name, code_hash=await hash_secret(code),
                      code_enc=core.box.encrypt(code), code_issued_at=utc_now())
    session.add(project)
    await session.flush()
    session.add(Section(project_id=project.id, slug=DEFAULT_SECTION[0], title=DEFAULT_SECTION[1]))
    owner = Member(project_id=project.id, external_id=owner_external_id, role=Role.OWNER,
                   display_name=(owner_display_name or "")[:128] or None, account=None)
    session.add(owner)
    await session.flush()
    link = await _ensure_account(core, session, project, owner, owner_login)
    await session.commit()
    return project, code, link or ""


async def list_projects(session: AsyncSession, integ: Integration, external_id: str | None,
                        limit: int, offset: int) -> list[tuple[Project, str | None]]:
    if external_id:
        rows = (await session.execute(
            select(Project, Member.role).join(Member, Member.project_id == Project.id)
            .where(Project.integration_id == integ.id, Member.external_id == check_external_id(external_id))
            .order_by(Project.id).limit(limit).offset(offset))).all()
        return [(p, r) for p, r in rows]
    rows = (await session.scalars(select(Project).where(Project.integration_id == integ.id)
                                  .order_by(Project.id).limit(limit).offset(offset))).all()
    return [(p, None) for p in rows]


async def rotate_code(core: Core, session: AsyncSession, project: Project) -> str:
    """New project code; the old one stops working at once. Open sessions stay (they were checked at login)."""
    code = new_project_code(project.public_id)
    project.code_hash, project.code_enc, project.code_issued_at = await hash_secret(code), core.box.encrypt(code), utc_now()
    await session.commit()
    return code


# ------------------------------------------------------------------ members
async def set_member(core: Core, session: AsyncSession, project: Project, acting_external_id: str, external_id: str,
                     role: str, display_name: str | None = None, login: str | None = None,
                     allowed_sections: list[str] | None | type[...] = ...) -> MemberResult:
    """Register an id with a status (or change it). `allowed_sections`: `...` — keep, None — all, list — only these."""
    acting = await require_member(session, project, acting_external_id)
    external_id = check_external_id(external_id)
    try:
        new_role = Role(role)
    except ValueError as e:
        raise bad_request("bad_role", "Статус: admin, support или user") from e
    if new_role is Role.OWNER:
        raise forbidden("owner_is_fixed", "Владелец назначается при создании проекта и не передаётся")
    target = await find_member(session, project, external_id)
    if target is not None and target.id == acting.id:
        raise forbidden("cannot_change_self", "Нельзя менять свой собственный статус")
    if target is not None and target.role == Role.OWNER:
        raise forbidden("owner_is_fixed", "Статус владельца не меняется")
    acting_role = Role(acting.role)
    if acting_role is Role.OWNER:
        pass
    elif acting_role is Role.ADMIN:
        if new_role is not Role.USER or (target is not None and target.role != Role.USER):
            raise forbidden("owner_only", "Админ управляет только пользователями; admin и support назначает владелец")
    else:
        raise forbidden("not_a_manager", "Управлять участниками могут только владелец и админы")

    if allowed_sections is not ... and allowed_sections is not None:
        unknown = set(allowed_sections) - await section_slugs(session, project)
        if unknown:
            raise bad_request("unknown_section", f"Нет таких разделов: {', '.join(sorted(unknown))}")

    if target is None:
        if await session.scalar(select(func.count()).select_from(Member).where(Member.project_id == project.id)) >= 100_000:
            raise conflict("members_limit", "Слишком много участников в проекте")
        target = Member(project_id=project.id, external_id=external_id, role=new_role, account=None)
        session.add(target)
        await session.flush()
    target.role = new_role
    if display_name is not None:
        target.display_name = display_name.strip()[:128] or None
    if allowed_sections is not ...:
        target.allowed_sections = list(dict.fromkeys(allowed_sections)) if allowed_sections is not None else None
    link = None
    if new_role.has_panel:
        link = await _ensure_account(core, session, project, target, login)
    elif target.account is not None:
        await session.execute(delete(PanelSession).where(PanelSession.account_id == target.account.id))
        target.account = None  # delete-orphan: no site access for a plain user
    await session.commit()
    await session.refresh(target)
    return MemberResult(target, link)


async def remove_member(session: AsyncSession, project: Project, acting_external_id: str, external_id: str) -> None:
    acting = await require_member(session, project, acting_external_id)
    target = await find_member(session, project, check_external_id(external_id))
    if target is None:
        raise not_found("member_not_found", "Участник не найден")
    if target.role == Role.OWNER:
        raise forbidden("owner_is_fixed", "Владельца нельзя удалить из проекта")
    if target.id == acting.id:
        raise forbidden("cannot_change_self", "Нельзя удалить самого себя")
    if acting.role == Role.ADMIN and target.role != Role.USER:
        raise forbidden("owner_only", "Админ может удалять только пользователей")
    if acting.role not in (Role.OWNER, Role.ADMIN):
        raise forbidden("not_a_manager", "Удалять участников могут только владелец и админы")
    await session.delete(target)
    await session.commit()


async def reset_panel_password(core: Core, session: AsyncSession, project: Project, acting_external_id: str,
                               external_id: str) -> str:
    """New one-time link to set the password: for oneself, or by the owner for anyone with a panel account."""
    acting = await require_member(session, project, acting_external_id)
    target = await find_member(session, project, check_external_id(external_id))
    if target is None or target.account is None:
        raise not_found("account_not_found", "У участника нет доступа к сайту")
    if target.id != acting.id and acting.role != Role.OWNER:
        raise forbidden("owner_only", "Сбросить чужой пароль может только владелец")
    link = await _setup_link(core, session, target.account)
    await session.commit()
    return link


def member_view(m: Member) -> dict:
    return {"external_id": m.external_id, "role": m.role, "display_name": m.display_name,
            "allowed_sections": m.allowed_sections, "panel_login": m.account.login if m.account else None,
            "panel_password_set": bool(m.account and m.account.password_hash),
            "created_at": m.created_at.isoformat(), "updated_at": m.updated_at.isoformat()}


def project_view(p: Project, role: str | None = None) -> dict:
    out = {"id": p.public_id, "name": p.name, "created_at": p.created_at.isoformat()}
    if role is not None:
        out["role"] = role
    return out
