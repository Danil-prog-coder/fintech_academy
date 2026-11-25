"""Тестовый доступ («Тестовый доступ для Fintech Academy» на странице входа).

Один клик — и гость (жюри) работает под общим демо-пользователем: ящик уже подключён,
проект с базой знаний выбран. Всё настраивается в .env (DEMO_*) и выключено по умолчанию.

Каждый вход заново приводит демо-аккаунт в рабочее состояние: если гость отключил ящик
или вышел из проекта, следующий вход вернёт их. Пароля у демо-пользователя нет (случайный
хеш), войти под ним можно только этой кнопкой.
"""

import logging
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mail_api.core.config import Settings
from mail_api.core.errors import AppError
from mail_api.core.security import decrypt_secret, encrypt_secret, hash_password
from mail_api.db.models import MailAccount, PlatformLink, User
from mail_api.services.mailbox.hosts import server_settings
from mail_api.services.platform import PlatformClient, external_id

log = logging.getLogger(__name__)


def is_demo_email(settings: Settings, email: str) -> bool:
    return settings.demo_enabled and email.lower() == settings.demo_user_email.lower()


async def demo_user(session: AsyncSession, settings: Settings, platform: PlatformClient) -> User:
    if not settings.demo_enabled:
        raise AppError("demo_disabled", "Тестовый доступ выключен.", 404)
    email = settings.demo_user_email.lower()
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, password_hash=await hash_password(secrets.token_urlsafe(32)))
        session.add(user)
        try:
            await session.commit()
        except IntegrityError:  # два гостя нажали одновременно
            await session.rollback()
            user = await session.scalar(select(User).where(User.email == email))
            if user is None:
                raise
    await _ensure_mailbox(session, settings, user)
    await _ensure_project(session, settings, platform, user)
    return user


async def _ensure_mailbox(session: AsyncSession, s: Settings, user: User) -> None:
    if not (s.demo_mailbox_email and s.demo_mailbox_password):
        return  # ящик не задан: гость подключит свой
    email = s.demo_mailbox_email.lower()
    account = await session.scalar(
        select(MailAccount).where(MailAccount.user_id == user.id, MailAccount.email == email)
    )
    if account is not None:
        if decrypt_secret(account.password_encrypted) != s.demo_mailbox_password:
            account.password_encrypted = encrypt_secret(s.demo_mailbox_password)  # пароль сменили в .env
            await session.commit()
        return
    try:
        servers = server_settings(
            email,
            s.demo_mailbox_imap_host or None,
            s.demo_mailbox_imap_port or None,
            s.demo_mailbox_imap_security or None,
            s.demo_mailbox_smtp_host or None,
            s.demo_mailbox_smtp_port or None,
            s.demo_mailbox_smtp_security or None,
        )
    except AppError:
        log.error("demo mailbox %s: unknown mail domain, set DEMO_MAILBOX_IMAP_HOST/SMTP_HOST", email)
        return
    # Пароль не проверяем: ящик задал администратор, а гость не должен ждать два логина на IMAP/SMTP.
    session.add(
        MailAccount(
            user_id=user.id,
            email=email,
            display_name=s.demo_mailbox_display_name or None,
            username=email,
            password_encrypted=encrypt_secret(s.demo_mailbox_password),
            imap_host=servers.imap_host,
            imap_port=servers.imap_port,
            imap_security=servers.imap_security,
            smtp_host=servers.smtp_host,
            smtp_port=servers.smtp_port,
            smtp_security=servers.smtp_security,
        )
    )
    await session.commit()


async def _ensure_project(
    session: AsyncSession, s: Settings, platform: PlatformClient, user: User
) -> None:
    """Вступает в демо-проект по коду (повторный вход по коду платформа принимает без изменений).

    С кодом проекта участник становится админом проекта, поэтому для демо нужен отдельный проект.
    Сбой платформы не мешает войти: почта работает и без неё.
    """
    if not s.demo_project_code:
        return
    try:
        res = await platform.join_project(
            external_id(user.id), s.demo_project_code, user.email, "Fintech Academy"
        )
        project_id = res["project"]["id"]
    except AppError as exc:
        log.warning("demo project: %s", exc.code)
        return
    link = await session.get(PlatformLink, user.id)
    if link is None:
        session.add(PlatformLink(user_id=user.id, current_project_id=project_id))
    else:
        link.current_project_id = project_id
    await session.commit()
