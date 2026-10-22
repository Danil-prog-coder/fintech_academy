"""Общая сборка внешних клиентов для API и worker."""

from contextlib import AsyncExitStack
from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.db.models import EMBEDDING_DIM
from app.llm.base import EmbeddingProvider, LLMProvider
from app.llm.cloudru import build_cloudru_embeddings
from app.llm.gigachat import build_gigachat, make_http_client
from app.llm.router import build_router
from app.llm.yandex import build_yandex
from app.services.github import GitHubClient


@dataclass
class Services:
    github: GitHubClient
    llm: LLMProvider | None
    embeddings: EmbeddingProvider | None


async def build_services(stack: AsyncExitStack, settings: Settings) -> Services:
    """Клиенты живут, пока открыт stack. Без ключей LLM-части остаются None."""
    use_cloudru = settings.embeddings_provider == "cloudru"
    dim_var, dim = (
        ("CLOUDRU_EMBEDDINGS_DIM", settings.cloudru_embeddings_dim)
        if use_cloudru
        else ("GIGACHAT_EMBEDDINGS_DIM", settings.gigachat_embeddings_dim)
    )
    if dim != EMBEDDING_DIM:
        raise RuntimeError(
            f"{dim_var}={dim}, а в БД вектор на "
            f"{EMBEDDING_DIM}: поменяйте размерность миграцией и переиндексируйте репозитории."
        )
    github_http = await stack.enter_async_context(
        httpx.AsyncClient(timeout=settings.llm_timeout_sec)
    )
    providers: dict[str, LLMProvider] = {}
    embeddings: EmbeddingProvider | None = None

    if settings.gigachat_credentials:
        giga_http = await stack.enter_async_context(make_http_client(settings))
        providers["gigachat"], giga_embeddings = build_gigachat(settings, giga_http)
        if not use_cloudru:
            embeddings = giga_embeddings
    if use_cloudru and settings.cloudru_api_key:
        # Отдельный клиент: Cloud.ru проверяется обычным хранилищем, а не российским CA-бандлом.
        cloudru_http = await stack.enter_async_context(
            httpx.AsyncClient(timeout=settings.llm_timeout_sec)
        )
        embeddings = build_cloudru_embeddings(settings, cloudru_http)
    if settings.yandex_api_key and settings.yandex_folder_id:
        yandex_http = await stack.enter_async_context(
            httpx.AsyncClient(timeout=settings.llm_timeout_sec)
        )
        yandex = build_yandex(settings, yandex_http)
        if yandex is not None:
            providers["yandex"] = yandex

    llm = build_router(providers, settings.llm_primary, settings.llm_fallback)
    return Services(github=GitHubClient(github_http), llm=llm, embeddings=embeddings)
