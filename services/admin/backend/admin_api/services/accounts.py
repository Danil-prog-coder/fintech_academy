"""Site accounts and sessions.

* A person registers on the site with a login and a password (`SiteUser`) and then works with projects:
  creates one (becomes its owner and sees the project code once), joins one as an admin with the project code, or
  attaches access given by an integration (a one-time link `…/setup?token=…`).
* Access to a project is a `PanelAccount` (owner / admin / support). A session remembers the chosen project; without
  a choice the site shows the project picker.
* Wrong login and wrong password look the same from outside; attempts are limited per IP and per login, attempts to
  guess a project code — per IP and per account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import Core
from ..db import utc_now
from ..errors import ApiError, bad_request, conflict, forbidden, not_found, unauthorized
from ..models import Integration, Member, PanelAccount, PanelSession, Project, Role, SetupToken, SiteUser
from ..security import (
    code_public_id,
    hash_secret,
    new_token,
    normalize_login,
    sha256,
    verify_secret,
)
from . import projects

SESSION_COOKIE = "panel_session"
BAD_CREDENTIALS = "Неверный логин или пароль"
BAD_CODE = "Неверный код проекта"
LINK_EXPIRED = "Ссылка недействительна или устарела — попросите новую"


def site_external_id(user: SiteUser) -> str:
    """The member id of a site account in projects it created or joined on the site."""
    return f"site:{user.id}"


@dataclass
class SiteSession:
    """A signed-in site account; `account` — access to the chosen project (None — no project chosen)."""

    user: SiteUser
    session_hash: str
    account: PanelAccount | None = None
    project: Project | None = None


@dataclass
class PanelUser:
    """A signed-in account inside its chosen project: what every page of the panel works with."""

    account: PanelAccount
    member: Member
    project: Project
    session_hash: str
    user: SiteUser | None = None

    @property
    def role(self) -> Role:
        return Role(self.member.role)


def check_password(password: str) -> None:
    """No rules on length or complexity — the person decides; only an empty password is refused."""
    if not password:
        raise bad_request("empty_password", "Введите пароль")


async def _limit(core: Core, key: str, attempts: int) -> None:
    if not await core.limiter.hit(key, attempts, core.settings.login_window_s):
        raise ApiError(429, "too_many_attempts", "Слишком много попыток, подождите немного", retryable=True)


async def _open_session(core: Core, session: AsyncSession, user: SiteUser, account: PanelAccount | None) -> str:
    token = new_token(32)
    session.add(PanelSession(token_hash=sha256(token), user_id=user.id, account_id=account.id if account else None,
                             expires_at=utc_now() + timedelta(hours=core.settings.session_ttl_hours)))
    await session.commit()
    return token


async def _accounts_of(session: AsyncSession, user: SiteUser) -> list[PanelAccount]:
    rows = (await session.scalars(select(PanelAccount).where(PanelAccount.user_id == user.id)
                                  .order_by(PanelAccount.id))).all()
    return [a for a in rows if Role(a.member.role).has_panel]


# ------------------------------------------------------------------ registration and login
async def register(core: Core, session: AsyncSession, login_: str, password: str, client_ip: str) -> tuple[str, SiteSession]:
    await _limit(core, f"register-ip:{client_ip}", core.settings.login_attempts)
    login_ = projects.check_login(login_)
    check_password(password)
    if await session.scalar(select(SiteUser.id).where(SiteUser.login == login_)) is not None:
        raise conflict("login_taken", "Такой логин уже занят — выберите другой или войдите")
    user = SiteUser(login=login_, password_hash=await hash_secret(password))
    session.add(user)
    await session.flush()
    token = await _open_session(core, session, user, None)
    return token, SiteSession(user, sha256(token))


async def login(core: Core, session: AsyncSession, login_: str, password: str, client_ip: str) -> tuple[str, SiteSession]:
    s = core.settings
    login_ = normalize_login(login_)
    await _limit(core, f"login-ip:{client_ip}", s.login_attempts * 3)
    await _limit(core, f"login:{login_}", s.login_attempts)
    user = await session.scalar(select(SiteUser).where(SiteUser.login == login_))
    if not await verify_secret(user.password_hash if user else None, password or "") or user is None:
        raise unauthorized(BAD_CREDENTIALS)
    await core.limiter.reset(f"login:{login_}", s.login_window_s)
    accounts = await _accounts_of(session, user)
    current = accounts[0] if len(accounts) == 1 else None  # one project — straight into it, several — the picker
    token = await _open_session(core, session, user, current)
    return token, SiteSession(user, sha256(token), current, await session.get(Project, current.project_id) if current else None)


async def resolve(session: AsyncSession, token: str | None) -> SiteSession | None:
    if not token:
        return None
    row = await session.get(PanelSession, sha256(token))
    if row is None or row.expires_at < utc_now():
        return None
    user = await session.get(SiteUser, row.user_id)
    if user is None:
        return None
    account = await session.get(PanelAccount, row.account_id) if row.account_id else None
    if account is None or account.user_id != user.id or not Role(account.member.role).has_panel:
        return SiteSession(user, row.token_hash)  # demoted or unlinked since: back to the picker
    return SiteSession(user, row.token_hash, account, await session.get(Project, account.project_id))


def panel_user(s: SiteSession) -> PanelUser | None:
    if s.account is None or s.project is None:
        return None
    return PanelUser(s.account, s.account.member, s.project, s.session_hash, s.user)


async def logout(session: AsyncSession, token_hash: str) -> None:
    await session.execute(delete(PanelSession).where(PanelSession.token_hash == token_hash))
    await session.commit()


async def _select(session: AsyncSession, s: SiteSession, account: PanelAccount) -> SiteSession:
    row = await session.get(PanelSession, s.session_hash)
    row.account_id = account.id
    await session.commit()
    await session.refresh(account, ["member", "user"])  # the caller reads them outside of the async context
    return SiteSession(s.user, s.session_hash, account, await session.get(Project, account.project_id))


# ------------------------------------------------------------------ projects of the account
async def my_projects(session: AsyncSession, s: SiteSession) -> list[dict]:
    out = []
    for a in await _accounts_of(session, s.user):
        p = await session.get(Project, a.project_id)
        out.append({**projects.project_view(p, a.member.role), "current": bool(s.account and s.account.id == a.id)})
    return out


async def select_project(session: AsyncSession, s: SiteSession, public_id: str) -> SiteSession:
    for a in await _accounts_of(session, s.user):
        p = await session.get(Project, a.project_id)
        if p.public_id == public_id:
            return await _select(session, s, a)
    raise not_found("project_not_found", "Проект не найден среди ваших")


async def _site_integration(core: Core, session: AsyncSession) -> Integration:
    """Projects created on the site belong to an integration too: its users are the ones who ask questions."""
    q = select(Integration).where(Integration.revoked_at.is_(None))
    slug = core.settings.site_projects_integration.strip()
    integ = await session.scalar(q.where(Integration.slug == slug) if slug else q.order_by(Integration.id).limit(1))
    if integ is None:
        raise ApiError(503, "no_integration", "На платформе нет подключённой интеграции, в которой можно работать с проектом",
                       retryable=True)
    return integ


async def create_project(core: Core, session: AsyncSession, s: SiteSession, name: str) -> tuple[SiteSession, str]:
    """→ (session in the new project, project code — shown once)."""
    await _limit(core, f"create-project:{s.user.id}", 20)
    integ = await _site_integration(core, session)
    owned = await session.scalar(select(func.count()).select_from(PanelAccount).join(Member, Member.id == PanelAccount.member_id)
                                 .where(PanelAccount.user_id == s.user.id, Member.role == Role.OWNER))
    if owned >= 50:
        raise conflict("projects_limit", "Слишком много проектов на одном аккаунте")
    project, code, _ = await projects.create_project(core, session, integ, name, site_external_id(s.user),
                                                     s.user.login, s.user.login, issue_link=False)
    owner = await projects.find_member(session, project, site_external_id(s.user))
    owner.account.user_id = s.user.id
    await session.commit()
    return await _select(session, s, owner.account), code


async def join_as_admin(core: Core, session: AsyncSession, s: SiteSession, code: str, client_ip: str) -> SiteSession:
    """The project code makes its holder an admin (the owner passes it only to helpers). A demoted admin does not get
    the rights back this way: only the owner can make him an admin again."""
    await _limit(core, f"join-ip:{client_ip}", core.settings.login_attempts * 3)
    await _limit(core, f"join:{s.user.id}", core.settings.login_attempts)
    public_id = code_public_id(code)
    project = await session.scalar(select(Project).where(Project.public_id == public_id)) if public_id else None
    if not await verify_secret(project.code_hash if project else None, (code or "").strip()) or project is None:
        raise forbidden("bad_project_code", BAD_CODE)
    for a in await _accounts_of(session, s.user):
        if a.project_id == project.id:
            return await _select(session, s, a)  # already in the project: just open it
    member = await projects.join_with_code(core, session, project, site_external_id(s.user), s.user.login, s.user.login)
    member.account.user_id = s.user.id
    await session.commit()
    return await _select(session, s, member.account)


# ------------------------------------------------------------------ links from integrations
async def _link_row(session: AsyncSession, token: str) -> tuple[SetupToken, PanelAccount]:
    row = await session.get(SetupToken, sha256(token or ""))
    if row is None or row.used_at is not None or row.expires_at < utc_now():
        raise ApiError(410, "link_expired", LINK_EXPIRED)
    account = await session.get(PanelAccount, row.account_id)
    if account is None or not Role(account.member.role).has_panel:
        raise ApiError(410, "link_expired", LINK_EXPIRED)
    return row, account


async def invite_info(session: AsyncSession, token: str) -> dict:
    _, account = await _link_row(session, token)
    project = await session.get(Project, account.project_id)
    return {"project": projects.project_view(project), "role": account.member.role, "login_hint": account.login,
            "display_name": account.member.display_name}


async def claim(session: AsyncSession, s: SiteSession, token: str) -> SiteSession:
    """Attach the access from the link to the signed-in site account and open that project."""
    row, account = await _link_row(session, token)
    other = await session.scalar(select(PanelAccount.id).where(PanelAccount.user_id == s.user.id,
                                                               PanelAccount.project_id == account.project_id,
                                                               PanelAccount.id != account.id))
    if other is not None:
        raise conflict("already_in_project", "У вашего аккаунта уже есть доступ к этому проекту")
    # a new link given by the owner moves the access: sessions of the previous site account drop to the picker
    account.user_id = s.user.id
    row.used_at = utc_now()
    await session.commit()
    return await _select(session, s, account)
