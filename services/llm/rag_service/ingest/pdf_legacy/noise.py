"""Header / footer / TOC noise filters for Confluence-exported Word PDFs."""

from __future__ import annotations

import re

# Repeated running header, e.g. "ЕИС – Функциональные возможности работы с БАРС-Офисом"
HEADER_RE = re.compile(r"^\s*ЕИС\s*[–—\-]")
STANDALONE_EIS_RE = re.compile(r"^\s*ЕИС\s*$")

# Word STYLEREF field that leaked into the footer of every page
FOOTER_ERROR_RE = re.compile(r'Ошибка!\s*Используйте вкладку\s+"Главная"', re.I)
FOOTER_CONT_RE = re.compile(r"должен здесь отображаться")
TOC_FOOTER_RE = re.compile(r"Table of Contents\s*[–—\-]\s*\d+", re.I)

EXPORTED_RE = re.compile(r"^\s*Exported on\b", re.I)
PAGE_ONLY_RE = re.compile(r"^\s*\d+\s*$")
DOT_LEADERS_RE = re.compile(r"\.{5,}")
TOC_TITLE_RE = re.compile(r"^\s*Table of Contents\s*$", re.I)

# Footer band in PDF points from the top of an A4 page (~841.9 pt)
HEADER_Y_MAX = 55.0
FOOTER_Y_MIN = 775.0


def is_noise_text(text: str, *, allow_bare_numbers: bool = False) -> bool:
    """Return True if `text` is a running header, footer or export artefact.

    `allow_bare_numbers=True` is used at the *word* level: a body word like
    "1000" or "14" must not be dropped just because page numbers also look
    like bare digits (those are already excluded by the header/footer y-band).
    """
    t = (text or "").strip()
    if not t:
        return True
    if HEADER_RE.match(t) or STANDALONE_EIS_RE.match(t):
        return True
    if FOOTER_ERROR_RE.search(t) or FOOTER_CONT_RE.search(t):
        return True
    if TOC_FOOTER_RE.search(t) or EXPORTED_RE.match(t):
        return True
    if not allow_bare_numbers and PAGE_ONLY_RE.match(t):
        return True
    if TOC_TITLE_RE.match(t):
        return True
    return False


def is_in_header_footer_band(top: float, page_height: float | None = None) -> bool:
    if top < HEADER_Y_MAX:
        return True
    footer_min = FOOTER_Y_MIN
    if page_height and page_height < 800:
        footer_min = page_height - 65
    return top > footer_min


def is_toc_leader_line(text: str) -> bool:
    return bool(DOT_LEADERS_RE.search(text or ""))
