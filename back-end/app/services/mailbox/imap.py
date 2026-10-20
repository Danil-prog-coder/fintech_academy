"""Работа с IMAP. Код синхронный (stdlib imaplib) и запускается через asyncio.to_thread.

На каждый запрос API открывается новое соединение: сервис ничего не хранит между запросами,
письма читаются с почтового сервера и в нашу БД не попадают.
"""

import imaplib
import re
import socket
import ssl
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Self

from app.services.mailbox import mutf7
from app.services.mailbox.errors import (
    auth_failed,
    folder_not_found,
    message_not_found,
    rejected,
    unavailable,
)

# Всё, что не IMAP-ответ, считаем недоступностью сервера.
_NETWORK_ERRORS = (OSError, ssl.SSLError, imaplib.IMAP4.abort, EOFError)


@dataclass(frozen=True)
class Conn:
    host: str
    port: int
    security: str  # ssl | starttls | none
    username: str
    password: str
    ip: str  # проверенный адрес, на который идёт соединение
    timeout: int


class _Imap(imaplib.IMAP4):
    """Подключается к заранее проверенному IP, а не к имени (защита от DNS rebinding)."""

    def __init__(self, host: str, port: int, ip: str, timeout: int):
        self._ip = ip
        super().__init__(host, port, timeout)

    def _create_socket(self, timeout):
        return socket.create_connection((self._ip, self.port), timeout)


class _ImapSSL(imaplib.IMAP4_SSL):
    def __init__(self, host: str, port: int, ip: str, timeout: int, ctx: ssl.SSLContext):
        self._ip = ip
        super().__init__(host, port, ssl_context=ctx, timeout=timeout)

    def _create_socket(self, timeout):
        sock = socket.create_connection((self._ip, self.port), timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def quote(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unquote(name: str) -> str:
    name = name.strip()
    if name.startswith('"') and name.endswith('"') and len(name) >= 2:
        return re.sub(r"\\(.)", r"\1", name[1:-1])
    return name


_LIST_RE = re.compile(
    r'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.+)$', re.DOTALL
)
_UID_RE = re.compile(rb"\bUID (\d+)")
_FLAGS_RE = re.compile(rb"FLAGS \(([^)]*)\)")
_SIZE_RE = re.compile(rb"RFC822\.SIZE (\d+)")
_STATUS_RE = re.compile(rb"MESSAGES (\d+)(?:.*?UNSEEN (\d+))?", re.DOTALL)

_ROLE_FLAGS = {
    "\\sent": "sent",
    "\\trash": "trash",
    "\\drafts": "drafts",
    "\\junk": "junk",
    "\\archive": "archive",
}
_ROLE_NAMES = {
    "sent": {"sent", "sent items", "sent messages", "отправленные", "исходящие"},
    "trash": {"trash", "deleted items", "deleted messages", "корзина", "удалённые", "удаленные"},
    "drafts": {"drafts", "draft", "черновики"},
    "junk": {"junk", "spam", "junk e-mail", "спам", "нежелательная почта"},
    "archive": {"archive", "архив"},
}


def folder_role(path: str, flags: set[str]) -> str | None:
    if path.upper() == "INBOX":
        return "inbox"
    for flag, role in _ROLE_FLAGS.items():
        if flag in flags:
            return role
    leaf = re.split(r"[/.]", path)[-1].strip().lower()
    for role, names in _ROLE_NAMES.items():
        if leaf in names:
            return role
    return None


@dataclass
class RawFolder:
    path: str  # декодированное имя, по нему клиент обращается к папке
    delimiter: str | None
    flags: set[str]
    role: str | None = None
    total: int = 0
    unseen: int = 0


@dataclass
class Fetched:
    flags: set[str] = field(default_factory=set)
    size: int = 0
    body: bytes = b""


def parse_fetch(data: list) -> dict[int, Fetched]:
    """Разбор ответа UID FETCH: метаданные могут идти до и после литерала."""
    out: dict[int, Fetched] = {}
    i = 0
    while i < len(data):
        item = data[i]
        if isinstance(item, tuple):
            meta, body = item[0], item[1]
            if i + 1 < len(data) and isinstance(data[i + 1], bytes):
                meta += data[i + 1]
                i += 1
        elif isinstance(item, bytes):
            meta, body = item, b""
        else:
            i += 1
            continue
        uid = _UID_RE.search(meta)
        if uid:
            flags = _FLAGS_RE.search(meta)
            size = _SIZE_RE.search(meta)
            entry = out.setdefault(int(uid.group(1)), Fetched())
            if flags:
                entry.flags = {f.decode().lower() for f in flags.group(1).split()}
            if size:
                entry.size = int(size.group(1))
            if body:
                entry.body = body
        i += 1
    return out


class ImapSession:
    def __init__(self, conn: Conn):
        self._c = conn
        self._imap: imaplib.IMAP4 | None = None
        self._folders: list[RawFolder] | None = None

    # --- соединение -------------------------------------------------------------------

    def __enter__(self) -> Self:
        c = self._c
        ctx = ssl.create_default_context()
        try:
            if c.security == "ssl":
                imap: imaplib.IMAP4 = _ImapSSL(c.host, c.port, c.ip, c.timeout, ctx)
            else:
                imap = _Imap(c.host, c.port, c.ip, c.timeout)
                if c.security == "starttls":
                    imap.starttls(ssl_context=ctx)
        except (*_NETWORK_ERRORS, imaplib.IMAP4.error):
            raise unavailable() from None
        self._imap = imap
        try:
            imap.login(quote(c.username), c.password)  # imaplib сам не квотирует логин
        except imaplib.IMAP4.abort:
            self._close()
            raise unavailable() from None
        except imaplib.IMAP4.error:
            self._close()
            raise auth_failed() from None
        except _NETWORK_ERRORS:
            self._close()
            raise unavailable() from None
        return self

    def __exit__(self, *exc) -> None:
        self._close()

    def _close(self) -> None:
        if self._imap is not None:
            with suppress(Exception):  # закрытие не должно маскировать основную ошибку
                self._imap.logout()
            self._imap = None

    @property
    def imap(self) -> imaplib.IMAP4:
        assert self._imap is not None
        return self._imap

    def _cmd(self, call, *args):
        """Выполняет команду imaplib, переводя сбои в ошибки API. Возвращает data при OK."""
        try:
            typ, data = call(*args)
        except _NETWORK_ERRORS:
            raise unavailable() from None
        except imaplib.IMAP4.error:
            raise rejected() from None
        if typ != "OK":
            raise rejected()
        return data

    def capabilities(self) -> set[str]:
        return {c.upper() for c in self.imap.capabilities}

    # --- папки ------------------------------------------------------------------------

    def folders(self) -> list[RawFolder]:
        if self._folders is None:
            data = self._cmd(self.imap.list)
            result: list[RawFolder] = []
            for item in data:
                if isinstance(item, tuple):
                    line = item[0].decode("utf-8", "replace")
                    line = re.sub(r"\{\d+\}$", "", line) + quote(item[1].decode("utf-8", "replace"))
                elif isinstance(item, bytes):
                    line = item.decode("utf-8", "replace")
                else:
                    continue
                m = _LIST_RE.match(line)
                if not m:
                    continue
                flags = {f.lower() for f in m.group("flags").split()}
                if "\\noselect" in flags or "\\nonexistent" in flags:
                    continue
                delim = m.group("delim")
                path = mutf7.decode(_unquote(m.group("name")))
                folder = RawFolder(
                    path=path, delimiter=None if delim == "NIL" else _unquote(delim), flags=flags
                )
                folder.role = folder_role(path, flags)
                result.append(folder)
            self._folders = result
        return self._folders

    def folder_status(self, folder: RawFolder) -> None:
        data = self._cmd(self.imap.status, quote(mutf7.encode(folder.path)), "(MESSAGES UNSEEN)")
        raw = data[0] if data and isinstance(data[0], bytes) else b""
        m = _STATUS_RE.search(raw)
        if m:
            folder.total = int(m.group(1))
            folder.unseen = int(m.group(2) or 0)

    def folder_by_role(self, role: str) -> RawFolder | None:
        return next((f for f in self.folders() if f.role == role), None)

    def create_folder(self, path: str) -> None:
        self._cmd(self.imap.create, quote(mutf7.encode(path)))
        self._folders = None

    def select(self, path: str, *, readonly: bool) -> int:
        try:
            typ, data = self.imap.select(quote(mutf7.encode(path)), readonly)
        except _NETWORK_ERRORS:
            raise unavailable() from None
        except imaplib.IMAP4.error:
            raise folder_not_found() from None
        if typ != "OK":
            raise folder_not_found()
        try:
            return int(data[0])
        except (TypeError, ValueError, IndexError):
            return 0

    # --- письма -----------------------------------------------------------------------

    def search(self, *, unread: bool = False, text: str | None = None) -> list[int]:
        criteria = ["UNSEEN"] if unread else []
        if text:
            # Не-ASCII допустим только литералом; TEXT с литералом должен идти последним.
            self.imap.literal = text.encode("utf-8")
            data = self._cmd(self.imap.uid, "SEARCH", "CHARSET", "UTF-8", *criteria, "TEXT")
        else:
            data = self._cmd(self.imap.uid, "SEARCH", *(criteria or ["ALL"]))
        raw = data[0] if data and isinstance(data[0], bytes) else b""
        return sorted(int(x) for x in raw.split())

    def fetch_headers(self, uids: list[int]) -> dict[int, Fetched]:
        if not uids:
            return {}
        fields = "FROM TO CC SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES CONTENT-TYPE"
        data = self._cmd(
            self.imap.uid,
            "FETCH",
            ",".join(map(str, uids)),
            f"(FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS ({fields})])",
        )
        return parse_fetch(data)

    def fetch_message(self, uid: int) -> Fetched:
        data = self._cmd(self.imap.uid, "FETCH", str(uid), "(FLAGS BODY.PEEK[])")
        found = parse_fetch(data).get(uid)
        if found is None or not found.body:
            raise message_not_found()
        return found

    def store_flags(self, uid: int, *, add: list[str], remove: list[str]) -> None:
        if add:
            self._cmd(self.imap.uid, "STORE", str(uid), "+FLAGS.SILENT", f"({' '.join(add)})")
        if remove:
            self._cmd(self.imap.uid, "STORE", str(uid), "-FLAGS.SILENT", f"({' '.join(remove)})")

    def _expunge(self, uid: int) -> None:
        if "UIDPLUS" in self.capabilities():
            self._cmd(self.imap.uid, "EXPUNGE", str(uid))
        else:
            self._cmd(self.imap.expunge)

    def move(self, uid: int, dest: str) -> None:
        target = quote(mutf7.encode(dest))
        if "MOVE" in self.capabilities():
            self._cmd(self.imap.uid, "MOVE", str(uid), target)
            return
        self._cmd(self.imap.uid, "COPY", str(uid), target)
        self.store_flags(uid, add=["\\Deleted"], remove=[])
        self._expunge(uid)

    def delete(self, uid: int) -> None:
        self.store_flags(uid, add=["\\Deleted"], remove=[])
        self._expunge(uid)

    def append(self, path: str, raw: bytes, flags: list[str]) -> None:
        target = quote(mutf7.encode(path))
        flag_arg = f"({' '.join(flags)})" if flags else None
        for attempt in (1, 2):
            try:
                typ, _ = self.imap.append(target, flag_arg, None, raw)
            except _NETWORK_ERRORS:
                raise unavailable() from None
            except imaplib.IMAP4.error:
                raise rejected() from None
            if typ == "OK":
                return
            if attempt == 1:
                self.create_folder(path)  # TRYCREATE: папки ещё нет
        raise rejected()
