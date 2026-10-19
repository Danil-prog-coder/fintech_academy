from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.errors import AppError


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMError(AppError):
    """Базовая ошибка LLM-слоя. Тексты ответов провайдера в сообщения не попадают."""


class LLMNotConfiguredError(LLMError):
    def __init__(self, provider: str):
        super().__init__(
            "llm_not_configured", f"Провайдер {provider} не настроен: нет ключей.", 503
        )


class LLMAuthError(LLMError):
    """Неверные ключи или нет прав. Fallback на запасного провайдера не включается."""

    def __init__(self, provider: str):
        super().__init__(
            "llm_auth_error", f"Провайдер {provider} отклонил авторизацию. Проверьте ключи.", 502
        )


class LLMUnavailableError(LLMError):
    """Таймаут, сеть, 429 или 5xx. Для такой ошибки допустим fallback."""

    def __init__(self, provider: str):
        super().__init__(
            "llm_unavailable", f"Провайдер {provider} временно недоступен.", 502, retryable=True
        )


class LLMResponseError(LLMError):
    """Провайдер ответил, но ответ неожиданного вида."""

    def __init__(self, provider: str, detail: str):
        super().__init__(
            "llm_bad_response", f"Некорректный ответ провайдера {provider}: {detail}.", 502
        )


class LLMProvider(Protocol):
    name: str

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult: ...

    def stream(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]: ...


class EmbeddingProvider(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
