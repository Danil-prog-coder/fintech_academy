"""Разбор черновика письма: какие вопросы задать платформе и что посоветовать пользователю."""

import re

from mail_api.schemas.mail import Recommendation

MAX_QUESTIONS = 5
_SENTENCE_RE = re.compile(r"[^?.!\n]*\?")


def extract_questions(draft: str) -> list[str]:
    """Предложения, оканчивающиеся на «?»; если их нет — весь черновик как один вопрос."""
    found = [m.group(0).strip() for m in _SENTENCE_RE.finditer(draft)]
    found = [q for q in found if len(q) > 1]
    if not found:
        found = [draft.strip()[:2000]]
    return found[:MAX_QUESTIONS]


def recommend(actions: list[str]) -> Recommendation:
    """Ответ найден на всё — письмо можно не отправлять; не найден ни на что — отправляйте."""
    if actions and all(a == "answer" for a in actions):
        return Recommendation.answer_found
    if not any(a == "answer" for a in actions):
        return Recommendation.no_answer
    return Recommendation.partial
