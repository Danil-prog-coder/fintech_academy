"""Model routing: fast tier for simple questions, heavy tier for everything else (NFR-01 latency / cost).

Simple = no screenshot, short self-contained question, not a procedure / table / comparison / multi-document /
regulation-number question, and the first search finds ONE confident fragment. The decision is made in two steps:
`initial_tier` (question text, before any LLM call) and `after_search` (retriever signals). Any doubt — a guardrail
retry, a plain-text reply, a weak or ambiguous search — moves the rest of the turn to the heavy tier; the tier never
goes back down within a turn. Citation / quote / number checks in code are the same on both paths.
"""

from __future__ import annotations

import re

from ..config import get_settings

_HEAVY_PATTERNS = [
    (r"поэтапн|пошагов|по шагам|шаг[аиов]*\b|как (?:настро|созда|добав|оформ|заполн|подат|выполн|сдела|запуст|исправ|удал)|инструкц|процедур|алгоритм", "procedure"),
    (r"таблиц|столбц|колонк|перечисл|список|какие\b.*\b(?:есть|бывают|существуют)|"
     r"какие (?:\w+ )?(?:статус|кнопк|пол[яей]|рол|функци|вид|тип|оператор|документ|раздел|шаг|этап|поля)|"
     r"все (?:виды|типы|статусы|поля|роли)", "table/list"),
    (r"сравн|отлич|разниц|чем .* от|лучше|versus|\bvs\b|или .*\?", "comparison"),
    (r"сколько|срок|лимит|норматив|процент|%|сумм|стоимост|тариф|sla|регламент|не позднее|не более|не менее|максимальн|минимальн", "numbers/regulation"),
    (r"почему|если|услови|развилк|в каком случае|когда нужно|можно ли|смогу ли|ошибк|не работает|не открывает|не могу", "conditions/troubleshooting"),
    (r"верси|релиз|изменилось|раньше|старой|новой", "versions"),
    (r"https?://|\d{3,}", "link/number in question"),
]


def initial_tier(text: str, has_images: bool, standalone: bool = True) -> tuple[str, str]:
    s = get_settings()
    if not s.routing_enabled:
        return "heavy", "routing off"
    if has_images:
        return "heavy", "screenshot"
    t = (text or "").lower().strip()
    if not t:
        return "heavy", "empty"
    words = len(t.split())
    if len(t) > s.route_fast_max_chars or words > s.route_fast_max_words:
        return "heavy", "long question"
    if t.count("?") > 1 or re.search(r"\bи\b.*\?.*\bи\b|;\s", t):
        return "heavy", "several questions"
    for pat, why in _HEAVY_PATTERNS:
        if re.search(pat, t):
            return "heavy", why
    if not standalone and words <= 3:
        return "heavy", "short follow-up needs dialog context"
    return "fast", "simple question"


def after_search(signals: dict) -> tuple[bool, str]:
    """→ (stay_fast, why). Fast tier only when one fragment clearly holds the answer."""
    s = get_settings()
    top = float(signals.get("max_score") or 0)
    gap = float(signals.get("gap_top1_top2") or 0)
    n = int(signals.get("n_supporting") or 0)
    if top < s.route_fast_min_score:
        return False, f"weak search (top={top:.2f})"
    if n > 1 and gap < s.route_fast_min_gap:
        return False, f"answer spread over {n} fragments"
    return True, "one confident fragment"
