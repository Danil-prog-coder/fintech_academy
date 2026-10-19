from fastapi import Request

from app.llm.base import EmbeddingProvider, LLMNotConfiguredError, LLMProvider


def get_llm(request: Request) -> LLMProvider:
    llm = getattr(request.app.state, "llm", None)
    if llm is None:
        raise LLMNotConfiguredError("gigachat")
    return llm


def get_embeddings(request: Request) -> EmbeddingProvider:
    embeddings = getattr(request.app.state, "embeddings", None)
    if embeddings is None:
        raise LLMNotConfiguredError("gigachat")
    return embeddings
