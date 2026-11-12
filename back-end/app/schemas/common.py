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

    id: int | None  # для GET /sources/{id}; None у вложений письма (их нет в индексе)
    path: str  # путь в репозитории или имя вложения
    kind: str  # code | doc | issue | pr | attachment
    commit_sha: str | None  # None у вложений
    snippet: str  # у вложений — фрагмент целиком
    url: str | None  # ссылка на файл в GitHub; None у вложений


ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}
