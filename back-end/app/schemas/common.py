from enum import StrEnum

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Единый формат ошибок (FR-REL-01)."""

    code: str
    message: str
    retryable: bool


class AnswerStatus(StrEnum):
    answered = "answered"
    partial = "partial"
    not_found = "not_found"
    out_of_scope = "out_of_scope"  # вопрос не относится к проекту


class Source(BaseModel):
    """Источник утверждения в ответе."""

    id: int  # для GET /sources/{id}
    path: str
    kind: str  # code | doc | issue | pr
    commit_sha: str
    snippet: str
    url: str  # ссылка на файл в GitHub


ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
