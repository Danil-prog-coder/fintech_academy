"""Оркестрация ответа.

Пока без поиска по индексу и генерации ответа: после проверки «относится ли вопрос к проекту»
любой вопрос получает `not_found`. Точка расширения — `answer_question`: сюда встанут
эмбеддинг вопроса, поиск по pgvector и генерация ответа.
"""

import hashlib
from dataclasses import dataclass, field

from app.db.models import Repository
from app.llm.base import LLMProvider
from app.schemas.common import AnswerStatus, Source
from app.services.scope import is_in_scope

NOT_FOUND_TEXT = "В проекте не найдено подтверждения для ответа на этот вопрос."
OUT_OF_SCOPE_TEXT = "Вопрос вне контекста проекта"


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
    repo: Repository,
    question: str,
    history: list[tuple[str, str]] | None = None,
    llm: LLMProvider | None = None,
) -> QAResult:
    """history — пары (role, text) предыдущих сообщений диалога.

    Если llm не настроен, проверка на принадлежность к проекту пропускается.
    """
    if llm is not None and not await is_in_scope(llm, repo, question, history):
        return QAResult(
            answer=OUT_OF_SCOPE_TEXT,
            status=AnswerStatus.out_of_scope,
            index_commit=repo.last_commit,
            provider=llm.name,
        )
    return QAResult(
        answer=NOT_FOUND_TEXT,
        status=AnswerStatus.not_found,
        index_commit=repo.last_commit,
        provider=llm.name if llm is not None else None,
    )
