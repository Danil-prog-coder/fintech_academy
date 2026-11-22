from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class ThreadMessage(BaseModel):
    author: str | None = Field(default=None, max_length=320)
    text: str = Field(max_length=20000)
    sent_at: datetime | None = None


class MailAskRequest(BaseModel):
    """«Спросить у ИИ» по черновику письма. Содержимое не сохраняется."""

    draft: str = Field(min_length=1, max_length=20000, description="Текст черновика письма.")
    subject: str | None = Field(default=None, max_length=500)
    recipients: list[EmailStr] = Field(default_factory=list, max_length=50, description="Только для контекста.")
    thread: list[ThreadMessage] = Field(default_factory=list, max_length=50, description="Цепочка переписки.")


class Recommendation(StrEnum):
    answer_found = "answer_found"  # письмо можно не отправлять
    partial = "partial"
    no_answer = "no_answer"  # ответа нет, отправьте письмо


class Source(BaseModel):
    label: str | None = None
    document_title: str | None = None
    section_path: str | None = None
    excerpt: str | None = None
    url: str | None = None


class QuestionResult(BaseModel):
    question: str
    request_id: str | None
    action: Literal["answer", "clarify", "offer_operator", "escalate"] | str
    answer: str
    sources: list[Source]
    confidence_level: str | None = None


class MailAskResponse(BaseModel):
    project_id: str
    results: list[QuestionResult]
    recommendation: Recommendation


class ReplyDraftRequest(BaseModel):
    """«Ответить с ИИ»: черновик ответа на входящее письмо по документации проекта. Ничего не отправляет и не сохраняет."""

    letter: str = Field(min_length=1, max_length=20000, description="Текст входящего письма, на которое отвечаем.")
    subject: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=320, description="Отправитель входящего письма.")


class ReplyDraftResponse(BaseModel):
    project_id: str
    draft: str = Field(description="Готовый текст ответа; пометки «[уточнить: …]» пользователь дописывает сам.")
    results: list[QuestionResult]
    todo: list[str] = Field(description="Вопросы письма, ответа на которые в документации нет.")
