"""Минимальные настоящие IMAP- и SMTP-серверы для e2e-тестов почтового клиента.

Серверы слушают локальные порты и говорят по сетевому протоколу, поэтому приложение
проходит весь путь: imaplib/smtplib → сокет → сервер. Реализовано ровно то, что нужно
клиенту: LOGIN, LIST, STATUS, SELECT/EXAMINE, UID SEARCH/FETCH/STORE/COPY/MOVE/EXPUNGE,
CREATE, APPEND (с литералами) и SMTP с AUTH PLAIN.
"""

import asyncio
import base64
import re
from dataclasses import dataclass, field
from email import message_from_bytes

from app.services.mailbox import mutf7

_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
_LITERAL = re.compile(rb"\{(\d+)\+?\}$")


@dataclass
class Msg:
    uid: int
    raw: bytes
    flags: set[str] = field(default_factory=set)


@dataclass
class Box:
    special: str | None = None  # \Sent, \Trash ...
    msgs: list[Msg] = field(default_factory=list)
    next_uid: int = 1

    def add(self, raw: bytes, flags: set[str] | None = None) -> Msg:
        msg = Msg(self.next_uid, raw, set(flags or ()))
        self.next_uid += 1
        self.msgs.append(msg)
        return msg


def _unq(token: str) -> str:
    return re.sub(r"\\(.)", r"\1", token)


class FakeMail:
    def __init__(
        self,
        user: str = "dev@mail.example.com",
        password: str = "app-password",
        *,
        move: bool = True,
        uidplus: bool = True,
    ):
        self.user, self.password = user, password
        self.caps = "IMAP4rev1" + (" UIDPLUS" if uidplus else "") + (" MOVE" if move else "")
        self.move_supported = move
        self.boxes: dict[str, Box] = {
            "INBOX": Box(),
            "Sent": Box("\\Sent"),
            "Drafts": Box("\\Drafts"),
            "Trash": Box("\\Trash"),
            "Проекты": Box(),
        }
        self.smtp_inbox: list[tuple[str, list[str], bytes]] = []  # (from, rcpts, data)
        self.smtp_rejects: set[str] = set()
        self.imap_logins = 0
        self.imap_port = 0
        self.smtp_port = 0
        self._servers: list[asyncio.Server] = []

    async def start(self) -> "FakeMail":
        imap = await asyncio.start_server(self._imap, "127.0.0.1", 0)
        smtp = await asyncio.start_server(self._smtp, "127.0.0.1", 0)
        self._servers = [imap, smtp]
        self.imap_port = imap.sockets[0].getsockname()[1]
        self.smtp_port = smtp.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        for server in self._servers:
            server.close()
            await server.wait_closed()

    # --- вспомогательное для тестов ----------------------------------------------------

    def add(self, box: str, raw: bytes, *flags: str) -> int:
        return self.boxes[box].add(raw, set(flags)).uid

    def uids(self, box: str) -> list[int]:
        return [m.uid for m in self.boxes[box].msgs]

    def find(self, box: str, uid: int) -> Msg | None:
        return next((m for m in self.boxes[box].msgs if m.uid == uid), None)

    # --- IMAP --------------------------------------------------------------------------

    async def _read_command(self, reader, writer) -> tuple[str, list[bytes]] | None:
        line = await reader.readline()
        if not line:
            return None
        literals: list[bytes] = []
        text = b""
        while True:
            m = _LITERAL.search(line.rstrip(b"\r\n"))
            if not m:
                text += line.rstrip(b"\r\n")
                break
            text += line.rstrip(b"\r\n")[: m.start()] + b"\x00LIT%d\x00" % len(literals)
            writer.write(b"+ go ahead\r\n")
            await writer.drain()
            literals.append(await reader.readexactly(int(m.group(1))))
            line = await reader.readline()
        return text.decode("utf-8", "replace"), literals

    def _box(self, token: str) -> tuple[str, Box] | None:
        m = _QUOTED.search(token)
        name = mutf7.decode(_unq(m.group(1)) if m else token.strip())
        box = self.boxes.get(name)
        return (name, box) if box is not None else None

    async def _imap(self, reader, writer) -> None:
        def send(data: str | bytes) -> None:
            writer.write(data.encode() if isinstance(data, str) else data)

        send(f"* OK [CAPABILITY {self.caps}] fake imap ready\r\n")
        authed = False
        selected: tuple[str, Box] | None = None
        try:
            while True:
                cmd = await self._read_command(reader, writer)
                if cmd is None:
                    break
                line, literals = cmd
                parts = line.split(" ", 2)
                tag, name = parts[0], (parts[1].upper() if len(parts) > 1 else "")
                rest = parts[2] if len(parts) > 2 else ""

                if name == "CAPABILITY":
                    send(f"* CAPABILITY {self.caps}\r\n{tag} OK done\r\n")
                elif name == "LOGOUT":
                    send(f"* BYE bye\r\n{tag} OK logout\r\n")
                    await writer.drain()
                    break
                elif name == "NOOP":
                    send(f"{tag} OK noop\r\n")
                elif name == "LOGIN":
                    creds = [_unq(x) for x in _QUOTED.findall(rest)]
                    if creds == [self.user, self.password]:
                        authed = True
                        self.imap_logins += 1
                        send(f"{tag} OK [CAPABILITY {self.caps}] logged in\r\n")
                    else:
                        send(f"{tag} NO [AUTHENTICATIONFAILED] invalid credentials\r\n")
                elif not authed:
                    send(f"{tag} BAD login first\r\n")
                elif name == "LIST":
                    for box_name, box in self.boxes.items():
                        attrs = "\\HasNoChildren" + (f" {box.special}" if box.special else "")
                        send(f'* LIST ({attrs}) "/" "{mutf7.encode(box_name)}"\r\n')
                    send(f"{tag} OK list done\r\n")
                elif name == "STATUS":
                    found = self._box(rest)
                    if found is None:
                        send(f"{tag} NO no such mailbox\r\n")
                    else:
                        box = found[1]
                        unseen = sum("\\seen" not in {f.lower() for f in m.flags} for m in box.msgs)
                        send(
                            f'* STATUS "{mutf7.encode(found[0])}" '
                            f"(MESSAGES {len(box.msgs)} UNSEEN {unseen})\r\n{tag} OK done\r\n"
                        )
                elif name in ("SELECT", "EXAMINE"):
                    found = self._box(rest)
                    if found is None:
                        send(f"{tag} NO no such mailbox\r\n")
                    else:
                        selected = found
                        mode = "READ-WRITE" if name == "SELECT" else "READ-ONLY"
                        send(
                            f"* {len(found[1].msgs)} EXISTS\r\n* 0 RECENT\r\n"
                            f"* OK [UIDVALIDITY 1] ok\r\n{tag} OK [{mode}] select done\r\n"
                        )
                elif name == "CREATE":
                    created = mutf7.decode(_unq(_QUOTED.search(rest).group(1)))
                    self.boxes.setdefault(created, Box())
                    send(f"{tag} OK created\r\n")
                elif name == "APPEND":
                    found = self._box(rest)
                    if found is None:
                        send(f"{tag} NO [TRYCREATE] no such mailbox\r\n")
                    else:
                        flags = re.search(r"\(([^)]*)\)", rest.split("\x00")[0])
                        msg = found[1].add(
                            literals[-1], set(flags.group(1).split()) if flags else set()
                        )
                        send(f"{tag} OK [APPENDUID 1 {msg.uid}] appended\r\n")
                elif name == "UID" and selected is not None:
                    self._uid_command(send, tag, rest, literals, selected)
                elif name == "EXPUNGE" and selected is not None:
                    self._expunge(send, selected[1], None)
                    send(f"{tag} OK expunged\r\n")
                elif name == "CLOSE":
                    selected = None
                    send(f"{tag} OK closed\r\n")
                else:
                    send(f"{tag} BAD unknown command\r\n")
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    def _expunge(self, send, box: Box, only_uid: int | None) -> None:
        for index in range(len(box.msgs), 0, -1):
            msg = box.msgs[index - 1]
            if "\\deleted" in {f.lower() for f in msg.flags} and only_uid in (None, msg.uid):
                del box.msgs[index - 1]
                send(f"* {index} EXPUNGE\r\n")

    @staticmethod
    def _uid_set(spec: str, box: Box) -> list[Msg]:
        wanted: set[int] = set()
        top = max((m.uid for m in box.msgs), default=0)
        for chunk in spec.split(","):
            lo, _, hi = chunk.partition(":")
            start = top if lo == "*" else int(lo)
            end = (top if hi == "*" else int(hi)) if hi else start
            wanted.update(range(min(start, end), max(start, end) + 1))
        return [m for m in box.msgs if m.uid in wanted]

    def _uid_command(self, send, tag, rest, literals, selected) -> None:
        box = selected[1]
        sub, _, args = rest.partition(" ")
        sub = sub.upper()
        if sub == "SEARCH":
            msgs = list(box.msgs)
            if "UNSEEN" in args:
                msgs = [m for m in msgs if "\\seen" not in {f.lower() for f in m.flags}]
            if "TEXT" in args:
                needle = literals[0].decode("utf-8").lower()
                msgs = [m for m in msgs if needle in m.raw.decode("utf-8", "replace").lower()]
            send("* SEARCH " + " ".join(str(m.uid) for m in msgs) + f"\r\n{tag} OK search done\r\n")
        elif sub == "FETCH":
            spec, _, items = args.partition(" ")
            for msg in self._uid_set(spec, box):
                send(self._fetch_one(box, msg, items))
            send(f"{tag} OK fetch done\r\n")
        elif sub == "STORE":
            spec, mode, flag_list = args.split(" ", 2)
            flags = set(flag_list.strip("()").split())
            for msg in self._uid_set(spec, box):
                if mode.startswith("+FLAGS"):
                    msg.flags |= flags
                elif mode.startswith("-FLAGS"):
                    msg.flags = {f for f in msg.flags if f.lower() not in {x.lower() for x in flags}}
            send(f"{tag} OK store done\r\n")
        elif sub in ("COPY", "MOVE"):
            spec, _, target = args.partition(" ")
            dest = self._box(target)
            if dest is None:
                send(f"{tag} NO [TRYCREATE] no such mailbox\r\n")
                return
            if sub == "MOVE" and not self.move_supported:
                send(f"{tag} BAD MOVE not supported\r\n")
                return
            for msg in self._uid_set(spec, box):
                dest[1].add(msg.raw, set(msg.flags) - {"\\Deleted"})
                if sub == "MOVE":
                    box.msgs.remove(msg)
            send(f"{tag} OK {sub.lower()} done\r\n")
        elif sub == "EXPUNGE":
            self._expunge(send, box, int(args))
            send(f"{tag} OK expunged\r\n")
        else:
            send(f"{tag} BAD unsupported uid command\r\n")

    def _fetch_one(self, box: Box, msg: Msg, items: str) -> bytes:
        seq = box.msgs.index(msg) + 1
        flags = " ".join(sorted(msg.flags))
        head = f"* {seq} FETCH (UID {msg.uid} FLAGS ({flags}) RFC822.SIZE {len(msg.raw)}"
        header_match = re.search(r"BODY\.PEEK\[HEADER\.FIELDS \(([^)]*)\)\]", items)
        if header_match:
            wanted = {f.lower() for f in header_match.group(1).split()}
            parsed = message_from_bytes(msg.raw)
            block = "".join(
                f"{k}: {v}\r\n" for k, v in parsed.raw_items() if k.lower() in wanted
            ).encode("utf-8", "surrogateescape") + b"\r\n"
            label = f"BODY[HEADER.FIELDS ({header_match.group(1)})]"
        else:
            block, label = msg.raw, "BODY[]"
        return head.encode() + f" {label} {{{len(block)}}}\r\n".encode() + block + b")\r\n"

    # --- SMTP --------------------------------------------------------------------------

    async def _smtp(self, reader, writer) -> None:
        def send(line: str) -> None:
            writer.write(line.encode() + b"\r\n")

        send("220 fake ESMTP ready")
        sender, rcpts, authed = "", [], False
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode().rstrip("\r\n")
                verb = line.split(" ", 1)[0].upper()
                if verb == "EHLO":
                    send("250-fake\r\n250-AUTH PLAIN\r\n250 8BITMIME")
                elif verb == "AUTH":
                    token = line.split(" ", 2)[2]
                    _, user, password = base64.b64decode(token).decode().split("\0")
                    authed = (user, password) == (self.user, self.password)
                    send("235 authenticated" if authed else "535 authentication failed")
                elif not authed and verb in ("MAIL", "RCPT", "DATA"):
                    send("530 authentication required")
                elif verb == "MAIL":
                    sender = re.search(r"<([^>]*)>", line).group(1)
                    rcpts = []
                    send("250 ok")
                elif verb == "RCPT":
                    rcpt = re.search(r"<([^>]*)>", line).group(1)
                    if rcpt in self.smtp_rejects:
                        send("550 no such user")
                    else:
                        rcpts.append(rcpt)
                        send("250 ok")
                elif verb == "DATA":
                    send("354 end with <CRLF>.<CRLF>")
                    await writer.drain()
                    data = await reader.readuntil(b"\r\n.\r\n")
                    body = data[: -len(b"\r\n.\r\n")] + b"\r\n"
                    self.smtp_inbox.append((sender, list(rcpts), body.replace(b"\r\n..", b"\r\n.")))
                    send("250 queued")
                elif verb == "RSET" or verb == "NOOP":
                    send("250 ok")
                elif verb == "QUIT":
                    send("221 bye")
                    await writer.drain()
                    break
                else:
                    send("502 not implemented")
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
