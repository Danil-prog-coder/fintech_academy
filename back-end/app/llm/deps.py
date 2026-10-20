from fastapi import Request

from app.llm.base import EmbeddingProvider, LLMNotConfiguredError, LLMProvider


def get_llm(request: Request) -> LLMProvider:
    llm = getattr(request.app.state, "llm", None)
    if llm is None:
        raise LLMNotConfiguredError("gigachat")
    return llm


def get_llm_optional(request: Request) -> LLMProvider | None:
    """Для функций, которые должны работать и без настроенного LLM (например, проверка оффтопа)."""
    return getattr(request.app.state, "llm", None)


def get_embeddings_optional(request: Request) -> EmbeddingProvider | None:
    return getattr(request.app.state, "embeddings", None)


def get_embeddings(request: Request) -> EmbeddingProvider:
    embeddings = getattr(request.app.state, "embeddings", None)
    if embeddings is None:
        raise LLMNotConfiguredError("gigachat")
    return embeddings
