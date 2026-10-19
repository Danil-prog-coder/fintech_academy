from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import AnswerStatus, Source


class ThreadMessage(BaseModel):
    author: str | None = Field(default=None, max_length=320)
    text: str = Field(max_length=20000)
    sent_at: datetime | None = None


class MailAskRequest(BaseModel):
    """Запрос от расширения. Содержимое не сохраняется (FR-MAIL-05)."""

    draft: str = Field(min_length=1, max_length=20000, description="Текст черновика письма.")
    subject: str | None = Field(default=None, max_length=500)
    recipients: list[EmailStr] = Field(
        default_factory=list, max_length=50, description="Только для контекста, не для отправки."
    )
    thread: list[ThreadMessage] = Field(
        default_factory=list, max_length=50, description="Цепочка текущей переписки."
    )


class Recommendation(StrEnum):
    answer_found = "answer_found"  # письмо можно не отправлять
    partial = "partial"
    no_answer = "no_answer"  # ответа нет, отправьте письмо


class QuestionResult(BaseModel):
    question_log_id: int  # к нему крепится оценка
    question: str
    answer: str
    status: AnswerStatus
    sources: list[Source]


class MailAskResponse(BaseModel):
    results: list[QuestionResult]
    recommendation: Recommendation
    index_commit: str | None
    provider: str | None
