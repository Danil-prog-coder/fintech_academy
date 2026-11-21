"""TOC parsing and heading detection."""

from __future__ import annotations

import re
import unicodedata

from .models import TocEntry

NUMBERED_HEADING_RE = re.compile(
    r"^(?P<num>\d+(?:\.\d+)*)(?:\s+)(?P<title>\S.*)$"
)

# "6.1 1. Замена билетов..." — TOC sometimes repeats a local number in the title
STRIP_LOCAL_NUM_RE = re.compile(r"^\d+\.\s+")

SHORT_TITLES = {
    "функциональные возможности работы с барс-офисом": "БАРС-Офис",
    "бп командировка": "БП Командировка",
    "реестр мебели": "Реестр мебели",
}


def normalize_spaces(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    text = text.replace("\u00a0", " ").replace("\u2009", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def normalize_title(text: str) -> str:
    t = normalize_spaces(text).strip(" .").lower().replace("ё", "е")
    t = re.sub(r"[«»\"“”„']", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def heading_level(number: str) -> int:
    return number.count(".") + 1


def parse_toc_text(text: str) -> list[TocEntry]:
    """Parse a 'Table of Contents' page dumped as plain text."""
    entries: list[TocEntry] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = normalize_spaces(raw)
        line = re.sub(r"\s*\.{2,}\s*", " ", line)
        line = re.sub(r"\s+\d+\s*$", "", line).strip()
        m = NUMBERED_HEADING_RE.match(line)
        if not m:
            continue
        number = m.group("num")
        title = normalize_spaces(m.group("title"))
        if number in seen:
            continue
        seen.add(number)
        entries.append(
            TocEntry(number=number, title=title, level=heading_level(number))
        )
    return entries


def short_doc_title(full_title: str) -> str:
    key = normalize_title(full_title)
    if key in SHORT_TITLES:
        return SHORT_TITLES[key]
    # already short enough
    if len(full_title.split()) <= 4:
        return full_title
    return full_title


def match_toc_entry(text: str, toc: list[TocEntry]) -> TocEntry | None:
    line = normalize_spaces(text)
    m = NUMBERED_HEADING_RE.match(line)
    if m:
        number = m.group("num")
        for e in toc:
            if e.number == number:
                return e
        # numbered heading not in TOC still counts
        title = normalize_spaces(m.group("title"))
        return TocEntry(number=number, title=title, level=heading_level(number))
    # unnumbered line that equals a TOC title (wrapped continuation already merged)
    norm = normalize_title(line)
    for e in toc:
        if normalize_title(e.title) == norm:
            return e
        # title without the local "1. " prefix
        if normalize_title(STRIP_LOCAL_NUM_RE.sub("", e.title)) == norm:
            return e
    return None


def section_path(short_title: str, trail: list[tuple[str, str]]) -> str:
    """trail is a list of (number, title) from level 1 down to the leaf."""
    parts = [short_title] + [title for _num, title in trail if title]
    # drop consecutive duplicates
    cleaned: list[str] = []
    for p in parts:
        p = p.strip().rstrip(".")
        if not p:
            continue
        if cleaned and normalize_title(cleaned[-1]) == normalize_title(p):
            continue
        cleaned.append(p)
    return " › ".join(cleaned)
