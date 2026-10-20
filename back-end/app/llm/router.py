"""Выбор провайдера и автоматический запасной.

При таймауте, ошибке сети, 429 и 5xx основного провайдера запрос один раз повторяется на
запасном. Ошибка авторизации (неверный ключ) молча не обходится: запасной не включается,
пользователь получает код ошибки провайдера.
"""

import logging
from collections.abc import AsyncIterator

from app.llm.base import (
    LLMAuthError,
    LLMProvider,
    LLMResponseError,
    LLMResult,
    LLMUnavailableError,
    Message,
)

log = logging.getLogger(__name__)


class FallbackLLM:
    """Реализует LLMProvider поверх основного и запасного провайдеров."""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider | None = None):
        self.primary, self.fallback = primary, fallback

    @property
    def name(self) -> str:
        return self.primary.name

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        try:
            return await self.primary.complete(
                messages, temperature=temperature, max_tokens=max_tokens
            )
        except (LLMUnavailableError, LLMResponseError) as exc:
            if self.fallback is None:
                raise
            log.warning("%s: %s, переключаемся на %s", self.primary.name, exc.code, self.fallback.name)
            return await self.fallback.complete(
                messages, temperature=temperature, max_tokens=max_tokens
            )

    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        started = False
        try:
            async for chunk in self.primary.stream(
                messages, temperature=temperature, max_tokens=max_tokens
            ):
                started = True
                yield chunk
            return
        except (LLMUnavailableError, LLMResponseError) as exc:
            # Если часть ответа уже ушла клиенту, подменять провайдера нельзя.
            if started or self.fallback is None:
                raise
            log.warning("%s: %s, переключаемся на %s", self.primary.name, exc.code, self.fallback.name)
        except LLMAuthError:
            raise
        async for chunk in self.fallback.stream(  # type: ignore[union-attr]
            messages, temperature=temperature, max_tokens=max_tokens
        ):
            yield chunk


def build_router(
    providers: dict[str, LLMProvider], primary: str, fallback: str
) -> FallbackLLM | None:
    """Только настроенные провайдеры. Если основной не настроен, его место занимает запасной."""
    first = providers.get(primary)
    second = providers.get(fallback) if fallback != primary else None
    if first is None and second is not None:
        log.warning("Основной провайдер %s не настроен, используется %s", primary, fallback)
        first, second = second, None
    if first is None:
        return None
    return FallbackLLM(first, second)
