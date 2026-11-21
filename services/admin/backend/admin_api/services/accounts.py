"""Site login: login + password + project code → an httpOnly session cookie.

* The project code identifies the project (its public part) and proves the person was given it by the owner.
* Wrong code, unknown login and wrong password look the same from outside: one message, comparable timing.
* Attempts are limited per IP and per (project, login).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import Core
from ..db import utc_now
from ..errors import ApiError, bad_request, unauthorized
from ..models import Member, PanelAccount, PanelSession, Project, Role, SetupToken
from ..security import (
    PASSWORD_MAX,
    PASSWORD_MIN,
    code_public_id,
    hash_secret,
    new_token,
    normalize_login,
    sha256,
    verify_secret,
)

SESSION_COOKIE = "panel_session"
BAD_CREDENTIALS = "Неверный логин, пароль или код проекта"


@dataclass
class PanelUser:
    account: PanelAccount
    member: Member
    project: Project
    session_hash: str

    @property
    def role(self) -> Role:
        return Role(self.member.role)


def check_password(password: str) -> None:
    if not (PASSWORD_MIN <= len(password or "") <= PASSWORD_MAX):
        raise bad_request("weak_password", f"Пароль: от {PASSWORD_MIN} до {PASSWORD_MAX} символов")
    if password.strip() != password or len(set(password)) < 4:
        raise bad_request("weak_password", "Пароль слишком простой")


async def setup_password(session: AsyncSession, token: str, password: str) -> dict:
    check_password(password)
    row = await session.get(SetupToken, sha256(token or ""))
    now = utc_now()
    if row is None or row.used_at is not None or row.expires_at < now:
        raise ApiError(410, "link_expired", "Ссылка недействительна или устарела — попросите новую")
    account = await session.get(PanelAccount, row.account_id)
    if account is None:
        raise ApiError(410, "link_expired", "Ссылка недействительна или устарела — попросите новую")
    account.password_hash = await hash_secret(password)
    account.password_set_at = now
    row.used_at = now
    # a new password ends every open session of the account
    await session.execute(delete(PanelSession).where(PanelSession.account_id == account.id))
    project = await session.get(Project, account.project_id)
    await session.commit()
    return {"login": account.login, "project_name": project.name if project else None}


async def login(core: Core, session: AsyncSession, login_: str, password: str, project_code: str,
                client_ip: str) -> tuple[str, PanelUser]:
    s = core.settings
    login_ = normalize_login(login_)
    if not await core.limiter.hit(f"login-ip:{client_ip}", s.login_attempts * 3, s.login_window_s) or \
            not await core.limiter.hit(f"login:{login_}", s.login_attempts, s.login_window_s):
        raise ApiError(429, "too_many_attempts", "Слишком много попыток входа, подождите немного", retryable=True)
    public_id = code_public_id(project_code)
    project = await session.scalar(select(Project).where(Project.public_id == public_id)) if public_id else None
    code_ok = await verify_secret(project.code_hash if project else None, (project_code or "").strip())
    account = None
    if project is not None:
        account = await session.scalar(select(PanelAccount).where(PanelAccount.project_id == project.id,
                                                                  PanelAccount.login == login_))
    password_ok = await verify_secret(account.password_hash if account else None, password or "")
    if not (code_ok and password_ok and account and Role(account.member.role).has_panel):
        raise unauthorized(BAD_CREDENTIALS)
    await core.limiter.reset(f"login:{login_}", s.login_window_s)
    token = new_token(32)
    row = PanelSession(token_hash=sha256(token), account_id=account.id,
                       expires_at=utc_now() + timedelta(hours=s.session_ttl_hours))
    session.add(row)
    await session.commit()
    return token, PanelUser(account, account.member, project, row.token_hash)


async def resolve(session: AsyncSession, token: str | None) -> PanelUser | None:
    if not token:
        return None
    row = await session.get(PanelSession, sha256(token))
    if row is None or row.expires_at < utc_now():
        return None
    account = await session.get(PanelAccount, row.account_id)
    if account is None or not Role(account.member.role).has_panel:
        return None
    project = await session.get(Project, account.project_id)
    return PanelUser(account, account.member, project, row.token_hash)


async def logout(session: AsyncSession, token_hash: str) -> None:
    await session.execute(delete(PanelSession).where(PanelSession.token_hash == token_hash))
    await session.commit()
