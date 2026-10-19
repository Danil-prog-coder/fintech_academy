"""Разбор черновика письма. Простая эвристика; позже выделение вопросов уйдёт в LLM."""

import re

from app.schemas.common import AnswerStatus
from app.schemas.mail import Recommendation

MAX_QUESTIONS = 5
_SENTENCE_RE = re.compile(r"[^?.!\n]*\?")


def extract_questions(draft: str) -> list[str]:
    """Предложения, оканчивающиеся на «?»; если их нет — весь черновик как один вопрос."""
    found = [m.group(0).strip() for m in _SENTENCE_RE.finditer(draft)]
    found = [q for q in found if len(q) > 1]
    if not found:
        found = [draft.strip()[:2000]]
    return found[:MAX_QUESTIONS]


def recommend(statuses: list[AnswerStatus]) -> Recommendation:
    if all(s == AnswerStatus.answered for s in statuses):
        return Recommendation.answer_found
    if all(s == AnswerStatus.not_found for s in statuses):
        return Recommendation.no_answer
    return Recommendation.partial
