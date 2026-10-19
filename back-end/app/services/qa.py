"""Оркестрация ответа.

Пока без подключения к нейросетям: поиска по индексу и генерации нет, поэтому
любой вопрос получает `not_found`. Точка расширения — `answer_question`: сюда
встанут эмбеддинг вопроса, поиск по pgvector и вызов LLM-слоя.
"""

import hashlib
from dataclasses import dataclass, field

from app.db.models import Repository
from app.schemas.common import AnswerStatus, Source

NOT_FOUND_TEXT = "В проекте не найдено подтверждения для ответа на этот вопрос."


@dataclass
class QAResult:
    answer: str
    status: AnswerStatus
    sources: list[Source] = field(default_factory=list)
    index_commit: str | None = None
    provider: str | None = None


def question_hash(question: str) -> str:
    return hashlib.sha256(question.strip().lower().encode()).hexdigest()


async def answer_question(
    repo: Repository, question: str, history: list[tuple[str, str]] | None = None
) -> QAResult:
    """history — пары (role, text) предыдущих сообщений диалога."""
    return QAResult(
        answer=NOT_FOUND_TEXT,
        status=AnswerStatus.not_found,
        index_commit=repo.last_commit,
    )
