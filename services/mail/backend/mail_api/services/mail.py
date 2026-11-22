"""Разбор писем: какие вопросы задать платформе, что посоветовать пользователю и как собрать черновик ответа."""

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


# ------------------------------------------------------------------ черновик ответа на входящее письмо
_CITATION_RE = re.compile(r"[ \t]*\[\d{1,3}\]")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_QUOTE_MAX = 120


def clean_answer(text: str) -> str:
    """Ответ платформы → абзац письма: без номеров источников (они показываются отдельно) и без Markdown."""
    text = _BOLD_RE.sub(r"\1", _CITATION_RE.sub("", text or ""))
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _short(question: str) -> str:
    question = " ".join(question.split())
    return question if len(question) <= _QUOTE_MAX else question[: _QUOTE_MAX - 1].rstrip() + "…"


def build_reply(items: list[tuple[str, str, str]]) -> tuple[str, list[str]]:
    """items: (вопрос из письма, action платформы, текст ответа) → (черновик, вопросы без ответа).

    Найденное в документации идёт абзацем на каждый вопрос; на что ответа нет, остаётся пометка
    «[уточнить: …]» — её пользователь заменяет сам, прежде чем нажать «Отправить»."""
    several = len(items) > 1
    paragraphs, todo = [], []
    for question, action, answer in items:
        text = clean_answer(answer) if action == "answer" else ""
        if not text:
            todo.append(question)
            text = f"[уточнить: {_short(question)}]"
        paragraphs.append(f"По вопросу «{_short(question)}»: {text}" if several else text)
    return "\n\n".join(["Здравствуйте!", *paragraphs, "С уважением,"]), todo
