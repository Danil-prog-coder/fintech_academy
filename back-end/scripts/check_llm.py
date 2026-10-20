"""Проверка настроенных ключей на живых серверах: python -m scripts.check_llm

Для каждого настроенного провайдера (GigaChat, YandexGPT) делает один короткий запрос и
проверяет эмбеддинги GigaChat (размерность должна совпасть с БД). Секреты не печатаются.
"""

import asyncio
import sys
from contextlib import AsyncExitStack

from app.core.config import get_settings
from app.core.runtime import build_services
from app.llm.base import LLMError, Message
from app.llm.router import FallbackLLM


async def main() -> int:
    settings = get_settings()
    failed = False
    async with AsyncExitStack() as stack:
        services = await build_services(stack, settings)
        if services.llm is None:
            print("Нет настроенных LLM: заполните GIGACHAT_CREDENTIALS и/или YANDEX_*.")
            return 1
        llm = services.llm
        providers = [llm.primary, llm.fallback] if isinstance(llm, FallbackLLM) else [llm]
        for provider in filter(None, providers):
            try:
                result = await provider.complete(
                    [Message("user", "Ответь одним словом: работает")], max_tokens=20
                )
                print(f"{provider.name}: ок ({result.text.strip()[:40]!r})")
            except LLMError as exc:
                failed = True
                print(f"{provider.name}: ОШИБКА {exc.code}: {exc.message}")
        if services.embeddings is not None:
            try:
                [vector] = await services.embeddings.embed(["проверка эмбеддингов"])
                print(f"эмбеддинги: ок, размерность {len(vector)}")
            except LLMError as exc:
                failed = True
                print(f"эмбеддинги: ОШИБКА {exc.code}: {exc.message}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
