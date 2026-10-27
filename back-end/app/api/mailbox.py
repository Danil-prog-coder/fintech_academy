"""Почтовый клиент: подключение ящиков по IMAP/SMTP, чтение, управление письмами, отправка.

Письма в нашей БД не хранятся — каждый запрос читает их с почтового сервера. В БД лежат
только настройки ящика и пароль приложения в зашифрованном виде.
"""

import asyncio
import base64
import binascii
import logging
from collections.abc import Callable
from urllib.parse import quote as url_quote

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.ratelimit import per_user
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import MailAccount, User
from app.db.session import get_session
from app.schemas.common import ERROR_RESPONSES
from app.schemas.mailbox import (
    AccountCreate,
    AccountOut,
    AddressOut,
    AttachmentOut,
    DraftResult,
    FolderOut,
    MessageList,
    MessageOut,
    MessagePatch,
    MessageSummary,
    SearchRequest,
    SendRequest,
    SendResult,
)
from app.services.mailbox import imap, parse, smtp
from app.services.mailbox.errors import folder_not_found, message_not_found, server_unavailable
from app.services.mailbox.hosts import resolve_public_host, saves_sent_copy, server_settings

log = logging.getLogger(__name__)
router = APIRouter(tags=["mailbox"], responses=ERROR_RESPONSES)

MAX_ACCOUNTS = 10
MAX_PAGE = 100
ROLE_ORDER = {"inbox": 0, "drafts": 1, "sent": 2, "archive": 3, "junk": 4, "trash": 5}


# --- вспомогательное ---------------------------------------------------------------------


def _out(account: MailAccount) -> AccountOut:
    return AccountOut(
        id=account.id,
        email=account.email,
        display_name=account.display_name,
        imap_host=account.imap_host,
        smtp_host=account.smtp_host,
        created_at=account.created_at,
    )


async def get_account(session: AsyncSession, user: User, account_id: int) -> MailAccount:
    account = await session.get(MailAccount, account_id)
    if account is None or account.user_id != user.id:
        raise AppError("mail_account_not_found", "Почтовый ящик не найден.", 404)
    return account


async def _imap_conn(account: MailAccount) -> imap.Conn:
    ip = await resolve_public_host(account.imap_host, account.imap_port, account.imap_security)
    return imap.Conn(
        host=account.imap_host,
        port=account.imap_port,
        security=account.imap_security,
        username=account.username,
        password=decrypt_secret(account.password_encrypted),
        ip=ip,
        timeout=get_settings().mail_timeout_sec,
    )


async def _smtp_conn(account: MailAccount) -> smtp.SmtpConn:
    ip = await resolve_public_host(account.smtp_host, account.smtp_port, account.smtp_security)
    return smtp.SmtpConn(
        host=account.smtp_host,
        port=account.smtp_port,
        security=account.smtp_security,
        username=account.username,
        password=decrypt_secret(account.password_encrypted),
        ip=ip,
        timeout=get_settings().mail_timeout_sec,
    )


async def run_imap[T](account: MailAccount, work: Callable[[imap.ImapSession], T]) -> T:
    """Открывает соединение, выполняет работу в потоке и закрывает соединение."""
    conn = await _imap_conn(account)

    def job() -> T:
        with imap.ImapSession(conn) as session:
            return work(session)

    return await asyncio.to_thread(job)


def _address(a: parse.Address | None) -> AddressOut | None:
    return AddressOut(name=a.name, email=a.email) if a else None


def _flag(flags: set[str], name: str) -> bool:
    return name in flags


def _is_unavailable(result: object) -> bool:
    return isinstance(result, AppError) and result.code == "mail_unavailable"


# --- ящики -------------------------------------------------------------------------------


@router.post("/mail/accounts", response_model=AccountOut, status_code=201)
async def connect_account(
    body: AccountCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    _: None = per_user("mail-connect", 10),
):
    email = body.email.lower()
    if not (body.password + (body.username or "")).isascii():
        raise AppError(
            "mail_credentials_unsupported", "Логин и пароль ящика должны быть в ASCII.", 422
        )
    count = await session.scalar(
        select(func.count()).select_from(MailAccount).where(MailAccount.user_id == user.id)
    )
    if (count or 0) >= MAX_ACCOUNTS:
        raise AppError("too_many_mail_accounts", "Подключено максимальное число ящиков.", 409)
    duplicate = await session.scalar(
        select(MailAccount).where(MailAccount.user_id == user.id, MailAccount.email == email)
    )
    if duplicate is not None:
        raise AppError("mail_account_exists", "Этот ящик уже подключён.", 409)

    servers = server_settings(
        email,
        body.imap_host,
        body.imap_port,
        body.imap_security,
        body.smtp_host,
        body.smtp_port,
        body.smtp_security,
    )
    account = MailAccount(
        user_id=user.id,
        email=email,
        display_name=body.display_name,
        username=body.username or email,
        password_encrypted=encrypt_secret(body.password),
        imap_host=servers.imap_host,
        imap_port=servers.imap_port,
        imap_security=servers.imap_security,
        smtp_host=servers.smtp_host,
        smtp_port=servers.smtp_port,
        smtp_security=servers.smtp_security,
    )
    # Пароль проверяем на обоих серверах до сохранения.
    imap_conn, smtp_conn = await asyncio.gather(_imap_conn(account), _smtp_conn(account))

    def check_imap() -> None:
        with imap.ImapSession(imap_conn):
            pass

    imap_result, smtp_result = await asyncio.gather(
        asyncio.to_thread(check_imap),
        asyncio.to_thread(smtp.check_login, smtp_conn),
        return_exceptions=True,
    )
    if _is_unavailable(imap_result):
        raise server_unavailable("IMAP", account.imap_host, account.imap_port)
    if isinstance(imap_result, BaseException):
        raise imap_result
    # IMAP уже подтвердил пароль. Недоступный SMTP (например, хостинг закрыл исходящие
    # SMTP-порты) не мешает читать почту, поэтому ящик сохраняем; отправка сообщит об ошибке.
    if _is_unavailable(smtp_result):
        log.warning("smtp check skipped: %s:%s unreachable", account.smtp_host, account.smtp_port)
    elif isinstance(smtp_result, BaseException):
        raise smtp_result
    session.add(account)
    await session.commit()
    return _out(account)


@router.get("/mail/accounts", response_model=list[AccountOut])
async def list_accounts(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    rows = await session.scalars(
        select(MailAccount).where(MailAccount.user_id == user.id).order_by(MailAccount.id)
    )
    return [_out(a) for a in rows]


@router.delete("/mail/accounts/{account_id}", status_code=204)
async def disconnect_account(
    account_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await get_account(session, user, account_id)
    await session.delete(account)
    await session.commit()


# --- папки и письма ----------------------------------------------------------------------


@router.get("/mail/accounts/{account_id}/folders", response_model=list[FolderOut])
async def list_folders(
    account_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await get_account(session, user, account_id)

    def work(s: imap.ImapSession) -> list[imap.RawFolder]:
        folders = s.folders()
        for folder in folders:
            s.folder_status(folder)
        return folders

    folders = await run_imap(account, work)
    folders.sort(key=lambda f: (ROLE_ORDER.get(f.role or "", 9), f.path.lower()))
    return [
        FolderOut(
            path=f.path,
            name=f.path.split(f.delimiter)[-1] if f.delimiter else f.path,
            role=f.role,  # type: ignore[arg-type]
            total=f.total,
            unseen=f.unseen,
        )
        for f in folders
    ]


async def _list_messages(
    account: MailAccount, folder: str, q: str | None, unread: bool, limit: int, offset: int
) -> MessageList:
    def work(s: imap.ImapSession) -> tuple[int, list[MessageSummary]]:
        s.select(folder, readonly=True)
        uids = s.search(unread=unread, text=q)
        page = uids[::-1][offset : offset + limit]
        fetched = s.fetch_headers(page)
        items: list[MessageSummary] = []
        for uid in page:
            entry = fetched.get(uid)
            if entry is None:
                continue
            h = parse.parse_headers(entry.body)
            items.append(
                MessageSummary(
                    uid=uid,
                    subject=h.subject,
                    sender=_address(h.sender),
                    to=[_address(a) for a in h.to],  # type: ignore[misc]
                    date=h.date,
                    snippet=None,
                    seen=_flag(entry.flags, r"\seen"),
                    flagged=_flag(entry.flags, r"\flagged"),
                    answered=_flag(entry.flags, r"\answered"),
                    draft=_flag(entry.flags, r"\draft"),
                    has_attachments=h.has_attachments,
                    size=entry.size,
                )
            )
        return len(uids), items

    total, items = await run_imap(account, work)
    return MessageList(folder=folder, total=total, items=items)


@router.get("/mail/accounts/{account_id}/messages", response_model=MessageList)
async def list_messages(
    account_id: int,
    folder: str = Query(default="INBOX", max_length=500),
    unread: bool = False,
    limit: int = Query(default=30, ge=1, le=MAX_PAGE),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Письма папки, новые сверху."""
    account = await get_account(session, user, account_id)
    return await _list_messages(account, folder, None, unread, limit, offset)


@router.post("/mail/accounts/{account_id}/messages/search", response_model=MessageList)
async def search_messages(
    account_id: int,
    body: SearchRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Поиск по тексту письма. Запрос идёт в теле, а не в URL, чтобы не попасть в журналы."""
    account = await get_account(session, user, account_id)
    return await _list_messages(
        account, body.folder, body.q, body.unread, body.limit, body.offset
    )


@router.get("/mail/accounts/{account_id}/messages/{uid}", response_model=MessageOut)
async def read_message(
    account_id: int,
    uid: int,
    folder: str = Query(default="INBOX", max_length=500),
    mark_read: bool = True,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await get_account(session, user, account_id)

    def work(s: imap.ImapSession) -> MessageOut:
        s.select(folder, readonly=not mark_read)
        fetched = s.fetch_message(uid)
        flags = set(fetched.flags)
        if mark_read and "\\seen" not in flags:
            s.store_flags(uid, add=["\\Seen"], remove=[])
            flags.add("\\seen")
        full, _ = parse.parse_full(fetched.body)
        p = full.parsed
        return MessageOut(
            uid=uid,
            folder=folder,
            message_id=p.message_id,
            in_reply_to=p.in_reply_to,
            references=p.references,
            subject=p.subject,
            sender=_address(p.sender),
            to=[_address(a) for a in p.to],  # type: ignore[misc]
            cc=[_address(a) for a in p.cc],  # type: ignore[misc]
            date=p.date,
            seen=_flag(flags, "\\seen"),
            flagged=_flag(flags, "\\flagged"),
            answered=_flag(flags, "\\answered"),
            text=full.text,
            html=full.html,
            remote_images_blocked=full.remote_images_blocked,
            attachments=[
                AttachmentOut(
                    index=a.index,
                    filename=a.filename,
                    content_type=a.content_type,
                    size=a.size,
                    inline=a.inline,
                    content_id=a.content_id,
                )
                for a in full.attachments
            ],
        )

    return await run_imap(account, work)


@router.get("/mail/accounts/{account_id}/messages/{uid}/attachments/{index}")
async def download_attachment(
    account_id: int,
    uid: int,
    index: int,
    folder: str = Query(default="INBOX", max_length=500),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await get_account(session, user, account_id)

    def work(s: imap.ImapSession) -> tuple[str, str, bytes]:
        s.select(folder, readonly=True)
        raw = s.fetch_message(uid).body
        _, msg = parse.parse_full(raw)
        for i, part in parse.iter_attachments(msg):
            if i == index:
                name = part.get_filename() or f"attachment-{index + 1}"
                return name, part.get_content_type(), part.get_payload(decode=True) or b""
        raise AppError("attachment_not_found", "Вложение не найдено.", 404)

    name, content_type, data = await run_imap(account, work)
    ascii_name = name.encode("ascii", "ignore").decode() or "attachment"
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name.replace(chr(34), '')}\"; "
                f"filename*=UTF-8''{url_quote(name)}"
            ),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.patch("/mail/accounts/{account_id}/messages/{uid}", status_code=204)
async def update_message(
    account_id: int,
    uid: int,
    body: MessagePatch,
    folder: str = Query(default="INBOX", max_length=500),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Прочитано/непрочитано, флажок, перенос в другую папку."""
    account = await get_account(session, user, account_id)

    def work(s: imap.ImapSession) -> None:
        s.select(folder, readonly=False)
        if uid not in s.fetch_headers([uid]):
            raise message_not_found()
        add: list[str] = []
        remove: list[str] = []
        for value, flag in ((body.seen, "\\Seen"), (body.flagged, "\\Flagged")):
            if value is True:
                add.append(flag)
            elif value is False:
                remove.append(flag)
        s.store_flags(uid, add=add, remove=remove)
        if body.move_to is not None:
            if body.move_to not in {f.path for f in s.folders()}:
                raise folder_not_found()
            s.move(uid, body.move_to)

    await run_imap(account, work)


@router.delete("/mail/accounts/{account_id}/messages/{uid}", status_code=204)
async def delete_message(
    account_id: int,
    uid: int,
    folder: str = Query(default="INBOX", max_length=500),
    permanent: bool = False,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """В корзину; из самой корзины (или с permanent=true) — безвозвратно."""
    account = await get_account(session, user, account_id)

    def work(s: imap.ImapSession) -> None:
        s.select(folder, readonly=False)
        if uid not in s.fetch_headers([uid]):
            raise message_not_found()
        trash = s.folder_by_role("trash")
        if permanent or trash is None or trash.path == folder:
            s.delete(uid)
        else:
            s.move(uid, trash.path)

    await run_imap(account, work)


# --- отправка ----------------------------------------------------------------------------


def _decode_attachments(body: SendRequest) -> list[smtp.OutAttachment]:
    limit = get_settings().mail_max_attachment_bytes
    out: list[smtp.OutAttachment] = []
    total = 0
    for a in body.attachments:
        try:
            data = base64.b64decode(a.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise AppError("invalid_attachment", "Вложение не в формате base64.", 422) from None
        total += len(data)
        if total > limit:
            raise AppError("attachment_too_large", "Вложения слишком большие.", 413)
        out.append(smtp.OutAttachment(a.filename, a.content_type, data))
    return out


def _build(account: MailAccount, body: SendRequest):
    try:
        return smtp.build_message(
            from_email=account.email,
            display_name=account.display_name,
            to=list(body.to),
            cc=list(body.cc),
            bcc=list(body.bcc),
            subject=body.subject,
            text=body.text,
            html=body.html,
            attachments=_decode_attachments(body),
            in_reply_to=body.in_reply_to,
            references=body.references,
        )
    except ValueError:
        raise AppError("invalid_message", "Недопустимые символы в заголовках письма.", 422) from None


@router.post("/mail/accounts/{account_id}/send", response_model=SendResult)
async def send_message(
    account_id: int,
    body: SendRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    _: None = per_user("mail-send", 30),
):
    """Отправляет письмо от имени ящика и кладёт копию в «Отправленные»."""
    account = await get_account(session, user, account_id)
    recipients = [*body.to, *body.cc, *body.bcc]
    if not recipients:
        raise AppError("no_recipients", "Укажите хотя бы одного получателя.", 422)
    if body.text is None and body.html is None and not body.attachments:
        raise AppError("empty_message", "Письмо пустое.", 422)

    msg = await asyncio.to_thread(_build, account, body)
    raw = msg.as_bytes()
    if len(raw) > get_settings().mail_max_send_bytes:
        raise AppError("message_too_large", "Письмо слишком большое.", 413)
    smtp_conn = await _smtp_conn(account)
    try:
        await asyncio.to_thread(smtp.send, smtp_conn, msg, account.email, list(recipients))
    except AppError as exc:
        if _is_unavailable(exc):
            raise server_unavailable("SMTP", account.smtp_host, account.smtp_port) from None
        raise

    # Письмо уже ушло: дальнейшие сбои не должны превращать ответ в ошибку.
    auto_saved = saves_sent_copy(account.smtp_host)
    saved = auto_saved
    if not auto_saved or body.answered:

        def after(s: imap.ImapSession) -> bool:
            stored = False
            if not auto_saved:
                sent = s.folder_by_role("sent")
                s.append(sent.path if sent else "Sent", raw, [r"\Seen"])
                stored = True
            if body.answered:
                s.select(body.answered.folder, readonly=False)
                s.store_flags(body.answered.uid, add=[r"\Answered"], remove=[])
            return stored

        try:
            saved = auto_saved or await run_imap(account, after)
        except AppError as exc:
            log.warning("post-send step failed: %s", exc.code)
    return SendResult(message_id=str(msg["Message-ID"]), saved_to_sent=saved)


@router.post("/mail/accounts/{account_id}/drafts", response_model=DraftResult, status_code=201)
async def save_draft(
    account_id: int,
    body: SendRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Сохраняет черновик в папку «Черновики» ящика. Ничего не отправляется."""
    account = await get_account(session, user, account_id)
    msg = await asyncio.to_thread(_build, account, body)
    raw = msg.as_bytes()

    def work(s: imap.ImapSession) -> str:
        drafts = s.folder_by_role("drafts")
        path = drafts.path if drafts else "Drafts"
        s.append(path, raw, ["\\Draft", "\\Seen"])
        return path

    folder = await run_imap(account, work)
    return DraftResult(message_id=str(msg["Message-ID"]), folder=folder)
