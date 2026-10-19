from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import AnswerStatus, Source


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = Field(
        default=None, description="Продолжить диалог; без него начинается новый."
    )
    stream: bool = Field(default=False, description="true — ответ потоком SSE.")


class AnswerResponse(BaseModel):
    conversation_id: int
    message_id: int  # id ответа, к нему крепится оценка
    answer: str
    status: AnswerStatus
    sources: list[Source]
    index_commit: str | None = Field(description="Коммит, по которому построен индекс.")
    provider: str | None = Field(description="Какой LLM-провайдер ответил.")


class MessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    text: str
    sources: list[Source] = []
    status: AnswerStatus | None = None
    created_at: datetime


class ConversationOut(BaseModel):
    id: int
    created_at: datetime
    messages: list[MessageOut]
