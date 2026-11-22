"""Имена папок IMAP передаются в «модифицированном UTF-7» (RFC 3501, 5.1.3)."""

import base64
import re

_ENCODED = re.compile(r"&([^-]*)-")


def encode(text: str) -> str:
    out: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            raw = "".join(pending).encode("utf-16-be")
            b64 = base64.b64encode(raw).decode().rstrip("=").replace("/", ",")
            out.append(f"&{b64}-")
            pending.clear()

    for ch in text:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            pending.append(ch)
    flush()
    return "".join(out)


def decode(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        chunk = match.group(1)
        if not chunk:
            return "&"
        chunk = chunk.replace(",", "/")
        chunk += "=" * (-len(chunk) % 4)
        try:
            return base64.b64decode(chunk).decode("utf-16-be")
        except (ValueError, UnicodeDecodeError):
            return match.group(0)

    return _ENCODED.sub(repl, text)
