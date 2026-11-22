"""Confluence/Word export noise cleaning (FR-ING-03) and broken-place detection (FR-ING-07).

All rules are pure functions over strings so they are unit-tested on fragments of the real documents.
"""

from __future__ import annotations

import re

# --- lines that are pure noise -------------------------------------------------------------
_NOISE_LINE_RES = [
    re.compile(r"Ошибка!\s*Используйте вкладку\s*[\"«“]?Главная", re.I),
    re.compile(r"должен здесь отображаться", re.I),
    re.compile(r"^\s*Exported on\b.*$", re.I),
    re.compile(r"^\s*ЕИС\s*[–—-]\s*.+$"),
    re.compile(r"^\s*ЕИС\s*$"),
    re.compile(r"^\s*Table of Contents(\s*[–—-]\s*\d+)?\s*$", re.I),
    re.compile(r"^\s*(стр\.?|страница|page)?\s*\d{1,3}\s*(из\s*\d{1,3})?\s*$", re.I),
    re.compile(r"^.*\.{5,}\s*\d*\s*$"),  # TOC dot leaders
]

FIGURE_ARTIFACT_RE = re.compile(r"^\s*Figure\s+\d+\s+\S+.*$", re.I)
VIDEO_LOST_RE = re.compile(r"Your browser does not support the HTML5 video element\.?", re.I)
EXTERNAL_REF_RE = re.compile(r"Подробнее:\s*(?P<title>Инструкция[^.\n]*)", re.I)
MORE_BY_LINK_RE = re.compile(r"Подробнее по ссылке\.?", re.I)

# glued boundaries: "сотрудникуОписание" / "\"Свободен\".Внесение" / "mebel.zip5. Массовое"
_GLUED_WORDS_RE = re.compile(r"(?<=[а-яё])(?=[А-ЯЁ][а-яё]{2,})")
_GLUED_SENTENCE_RE = re.compile(r"(?:(?<=[а-яё]{3})|(?<=[»\"”)]))\.(?=[А-ЯЁ][а-яё])")
_GLUED_HEADING_RE = re.compile(r"(?<=[a-zа-яё.»\"”)])(?=\d{1,2}\.\s+[А-ЯЁ][а-яё])")

# words that legitimately contain a lowercase->Uppercase transition (camel case in product names)
_CAMEL_WHITELIST = ("БарсОфис", "БАРС", "МедМИС")


def is_noise_line(line: str) -> bool:
    return any(r.search(line) for r in _NOISE_LINE_RES)


def fix_glued(text: str) -> str:
    """Restore boundaries lost on export (FR-ING-03)."""
    if any(w in text for w in _CAMEL_WHITELIST):
        protected = text
        for i, w in enumerate(_CAMEL_WHITELIST):
            protected = protected.replace(w, f"\uE000{i}\uE001")
    else:
        protected = text
    protected = _GLUED_HEADING_RE.sub("\n", protected)
    protected = _GLUED_SENTENCE_RE.sub(".\n", protected)
    protected = _GLUED_WORDS_RE.sub("\n", protected)
    for i, w in enumerate(_CAMEL_WHITELIST):
        protected = protected.replace(f"\uE000{i}\uE001", w)
    return protected


def clean_text(text: str, warnings: list[str] | None = None, where: str = "") -> str:
    """Drop noise lines, mark lost media / external refs, fix glued words."""
    out: list[str] = []
    for line in text.splitlines():
        if is_noise_line(line):
            continue
        if FIGURE_ARTIFACT_RE.match(line):
            if warnings is not None:
                warnings.append(f"artifact_caption: '{line.strip()}' {where}".strip())
            continue
        if VIDEO_LOST_RE.search(line):
            if warnings is not None:
                warnings.append(f"lost_video {where}".strip())
            line = VIDEO_LOST_RE.sub("[видео не сохранилось]", line)
        m = EXTERNAL_REF_RE.search(line)
        if m:
            title = m.group("title").strip()
            if warnings is not None:
                warnings.append(f"external_ref: '{title}' {where}".strip())
            line = EXTERNAL_REF_RE.sub(f"[внешняя инструкция: {title} — в базе знаний отсутствует]", line)
        if MORE_BY_LINK_RE.search(line):
            if warnings is not None:
                warnings.append(f"external_link {where}".strip())
            line = MORE_BY_LINK_RE.sub("[внешняя ссылка — в базе знаний отсутствует]", line)
        out.append(line)
    cleaned = "\n".join(out)
    cleaned = fix_glued(cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def mentions_video(text: str) -> bool:
    return bool(re.search(r"видео", text, re.I))


EMPTY_STEP_RE = re.compile(r"^\s*\d{1,2}[.)]\s*$")


def is_empty_step(text: str) -> bool:
    return bool(EMPTY_STEP_RE.match(text)) or not text.strip()
