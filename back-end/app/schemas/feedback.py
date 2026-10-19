from typing import Self

from pydantic import BaseModel, Field, model_validator


class FeedbackRequest(BaseModel):
    """Оценка ответа: чат — `message_id`, почта — `question_log_id`. Ровно одно из двух."""

    message_id: int | None = None
    question_log_id: int | None = None
    helpful: bool
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _exactly_one_target(self) -> Self:
        if (self.message_id is None) == (self.question_log_id is None):
            raise ValueError("укажите ровно одно из: message_id, question_log_id")
        return self


class FeedbackResponse(BaseModel):
    id: int
