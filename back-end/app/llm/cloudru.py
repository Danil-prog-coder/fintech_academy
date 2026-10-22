"""Эмбеддинги Cloud.ru Foundation Models (OpenAI-совместимый /v1/embeddings, модель BAAI/bge-m3)."""

import asyncio
import logging

import httpx

from app.core.config import Settings
from app.llm.base import LLMAuthError, LLMResponseError, LLMUnavailableError

log = logging.getLogger(__name__)

PROVIDER = "cloudru"


class CloudRuEmbeddings:
    name = PROVIDER

    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        base_url: str,
        *,
        model: str,
        dim: int,
        batch_size: int = 16,
        concurrency: int = 3,
        max_retries: int = 2,
        backoff_sec: float = 0.5,
    ):
        self._http, self._key = http, api_key
        self._base_url = base_url.rstrip("/")
        self._model, self.dim, self._batch = model, dim, batch_size
        self._retries, self._backoff = max_retries, backoff_sec
        self._semaphore = asyncio.Semaphore(concurrency)

    async def _post(self, batch: list[str]) -> dict:
        """POST с повторами на 429/5xx/сетевые сбои."""
        attempt = 0
        while True:
            try:
                r = await self._http.post(
                    f"{self._base_url}/embeddings",
                    json={"model": self._model, "input": batch},
                    headers={"Authorization": f"Bearer {self._key}"},
                )
                status = r.status_code
            except httpx.HTTPError:
                status = None

            if status is None or status == 429 or status >= 500:
                if attempt >= self._retries:
                    raise LLMUnavailableError(PROVIDER)
                await asyncio.sleep(self._backoff * 2**attempt)
                attempt += 1
                continue
            if status in (401, 403):
                raise LLMAuthError(PROVIDER)
            if status >= 400:
                raise LLMResponseError(PROVIDER, f"код {status}")
            try:
                return r.json()
            except ValueError:
                raise LLMResponseError(PROVIDER, "ответ не JSON") from None

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        async with self._semaphore:
            data = await self._post(batch)
        try:
            items = sorted(data["data"], key=lambda item: item.get("index", 0))
            vectors = [item["embedding"] for item in items]
        except (KeyError, TypeError):
            raise LLMResponseError(PROVIDER, "нет data[].embedding") from None
        if len(vectors) != len(batch):
            raise LLMResponseError(PROVIDER, "число векторов не совпало с числом текстов")
        if any(len(v) != self.dim for v in vectors):
            raise LLMResponseError(
                PROVIDER, f"размерность вектора не равна {self.dim}; проверьте CLOUDRU_EMBEDDINGS_DIM"
            )
        return vectors

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Векторы в том же порядке, что и тексты. Пакеты идут параллельно (с лимитом)."""
        batches = [texts[i : i + self._batch] for i in range(0, len(texts), self._batch)]
        results = await asyncio.gather(*(self._embed_batch(b) for b in batches))
        return [vector for batch in results for vector in batch]


def build_cloudru_embeddings(settings: Settings, http: httpx.AsyncClient) -> CloudRuEmbeddings:
    return CloudRuEmbeddings(
        http,
        settings.cloudru_api_key,
        settings.cloudru_base_url,
        model=settings.cloudru_embeddings_model,
        dim=settings.cloudru_embeddings_dim,
        batch_size=settings.cloudru_embeddings_batch,
        concurrency=settings.cloudru_embeddings_concurrency,
        max_retries=settings.gigachat_max_retries,
    )
