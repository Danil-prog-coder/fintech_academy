"""Проверка подключения к GigaChat на живых ключах.

Запуск из back-end/ после заполнения .env:
    python -m scripts.check_gigachat
"""

import asyncio

from app.core.config import get_settings
from app.llm.base import LLMError, Message
from app.llm.gigachat import build_gigachat, make_http_client


async def main() -> None:
    settings = get_settings()
    if not settings.gigachat_credentials:
        raise SystemExit("GIGACHAT_CREDENTIALS не задан в .env")

    async with make_http_client(settings) as http:
        llm, embeddings = build_gigachat(settings, http)

        print("1/3 чат...")
        result = await llm.complete([Message("user", "Ответь одним словом: привет")], max_tokens=20)
        print(f"   ответ: {result.text!r}, модель: {result.model}, "
              f"токены: {result.prompt_tokens}+{result.completion_tokens}")

        print("2/3 поток...")
        chunks = [c async for c in llm.stream([Message("user", "Посчитай до трёх")], max_tokens=40)]
        print(f"   получено {len(chunks)} фрагментов: {''.join(chunks)!r}")

        print("3/3 эмбеддинги...")
        vectors = await embeddings.embed(["Как настроен деплой?", "Процесс релиза"])
        print(f"   векторов: {len(vectors)}, размерность: {len(vectors[0])} "
              f"(в конфиге GIGACHAT_EMBEDDINGS_DIM={embeddings.dim})")

    print("OK")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except LLMError as e:
        raise SystemExit(f"Ошибка [{e.code}]: {e.message}") from None
