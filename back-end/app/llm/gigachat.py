"""Адаптер GigaChat: авторизация, чат (обычный и потоковый), эмбеддинги.

Эндпоинты и формат запросов написаны по публичной документации GigaChat API и ещё не
проверены на живых ключах — сверьте с актуальной документацией (см. scripts/check_gigachat.py).
"""

import asyncio
import json
import logging
import os
import ssl
import time
import uuid
from collections.abc import AsyncIterator, Callable

import certifi
import httpx

from app.core.config import Settings
from app.llm.base import (
    LLMAuthError,
    LLMResponseError,
    LLMResult,
    LLMUnavailableError,
    Message,
)
from app.llm.russian_ca import RUSSIAN_TRUSTED_CA

log = logging.getLogger(__name__)

PROVIDER = "gigachat"
TOKEN_MARGIN_SEC = 60  # обновляем токен заранее, до истечения


class GigaChatAuth:
    """Двухшаговая авторизация: Authorization key + scope -> короткоживущий access-токен.

    Токен кэшируется в памяти процесса; обновление идёт под Lock, чтобы параллельные
    запросы не запрашивали токен одновременно.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        credentials: str,
        scope: str,
        auth_url: str,
        *,
        clock: Callable[[], float] = time.time,
    ):
        key = credentials.strip()
        if key.lower().startswith("basic "):
            key = key[6:].strip()
        self._http, self._key, self._scope, self._url = http, key, scope, auth_url
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def _valid(self) -> bool:
        return self._token is not None and self._clock() < self._expires_at - TOKEN_MARGIN_SEC

    async def get_token(self) -> str:
        if self._valid():
            return self._token  # type: ignore[return-value]
        async with self._lock:
            if self._valid():
                return self._token  # type: ignore[return-value]
            await self._fetch()
            return self._token  # type: ignore[return-value]

    def invalidate(self, token: str) -> None:
        """Сбросить токен, который сервер отклонил (если его ещё не успели заменить)."""
        if self._token == token:
            self._token = None

    async def _fetch(self) -> None:
        headers = {
            "Authorization": f"Basic {self._key}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        try:
            r = await self._http.post(self._url, headers=headers, data={"scope": self._scope})
        except httpx.HTTPError as exc:
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                log.error(
                    "GigaChat: TLS-сертификат не принят, хотя сертификат российского УЦ встроен. "
                    "Проверьте GIGACHAT_AUTH_URL и прокси/VPN между сервером и GigaChat."
                )
            raise LLMUnavailableError(PROVIDER) from None
        if r.status_code in (400, 401, 403):
            raise LLMAuthError(PROVIDER)
        if r.status_code == 429 or r.status_code >= 500:
            raise LLMUnavailableError(PROVIDER)
        if r.status_code != 200:
            raise LLMResponseError(PROVIDER, f"авторизация вернула код {r.status_code}")
        try:
            data = r.json()
            self._token = data["access_token"]
            # expires_at приходит в миллисекундах Unix-времени
            self._expires_at = float(data["expires_at"]) / 1000
        except (ValueError, KeyError, TypeError):
            raise LLMResponseError(PROVIDER, "нет access_token в ответе авторизации") from None


class _GigaChatBase:
    def __init__(
        self,
        http: httpx.AsyncClient,
        auth: GigaChatAuth,
        base_url: str,
        *,
        max_retries: int = 2,
        backoff_sec: float = 0.5,
    ):
        self._http, self._auth = http, auth
        self._base_url = base_url.rstrip("/")
        self._retries, self._backoff = max_retries, backoff_sec

    async def _sleep(self, attempt: int) -> None:
        await asyncio.sleep(self._backoff * (2**attempt))

    async def _post_json(self, path: str, payload: dict) -> dict:
        """POST с повторами на 429/5xx/сетевые сбои и одним обновлением токена на 401."""
        refreshed = False
        attempt = 0
        while True:
            token = await self._auth.get_token()
            try:
                r = await self._http.post(
                    f"{self._base_url}{path}",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
                status = r.status_code
            except httpx.HTTPError:
                status = None

            if status == 401 and not refreshed:
                self._auth.invalidate(token)
                refreshed = True
                continue
            if status is None or status == 429 or status >= 500:
                if attempt >= self._retries:
                    raise LLMUnavailableError(PROVIDER)
                await self._sleep(attempt)
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


class GigaChatProvider(_GigaChatBase):
    name = PROVIDER

    def __init__(self, *args, model: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._model = model

    def _payload(
        self,
        messages: list[Message],
        *,
        stream: bool,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict:
        payload: dict = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        data = await self._post_json(
            "/chat/completions",
            self._payload(messages, stream=False, temperature=temperature, max_tokens=max_tokens),
        )
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMResponseError(PROVIDER, "нет choices[0].message.content") from None
        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            provider=PROVIDER,
            model=data.get("model", self._model),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, stream=True, temperature=temperature, max_tokens=max_tokens)
        refreshed = False
        attempt = 0
        while True:
            token = await self._auth.get_token()
            started = False
            try:
                async with self._http.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
                ) as r:
                    status = r.status_code
                    if status == 200:
                        async for line in r.aiter_lines():
                            delta = _parse_sse_line(line)
                            if delta is _DONE:
                                return
                            if delta:
                                started = True
                                yield delta
                        return
            except httpx.HTTPError:
                if started:
                    raise LLMUnavailableError(PROVIDER) from None
                status = None

            if status == 401 and not refreshed:
                self._auth.invalidate(token)
                refreshed = True
                continue
            if status is None or status == 429 or status >= 500:
                if attempt >= self._retries:
                    raise LLMUnavailableError(PROVIDER)
                await self._sleep(attempt)
                attempt += 1
                continue
            if status in (401, 403):
                raise LLMAuthError(PROVIDER)
            raise LLMResponseError(PROVIDER, f"код {status}")


_DONE = object()


def _parse_sse_line(line: str):
    """Возвращает текст дельты, _DONE для [DONE] или None для служебных строк."""
    line = line.strip()
    if not line.startswith("data:"):
        return None
    body = line[5:].strip()
    if body == "[DONE]":
        return _DONE
    try:
        return json.loads(body)["choices"][0]["delta"].get("content") or None
    except (ValueError, KeyError, IndexError, TypeError):
        return None


class GigaChatEmbeddings(_GigaChatBase):
    name = PROVIDER

    def __init__(
        self, *args, model: str, dim: int, batch_size: int = 32, concurrency: int = 3, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self._model, self.dim, self._batch = model, dim, batch_size
        self._semaphore = asyncio.Semaphore(concurrency)

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        async with self._semaphore:
            data = await self._post_json("/embeddings", {"model": self._model, "input": batch})
        try:
            items = sorted(data["data"], key=lambda item: item.get("index", 0))
            vectors = [item["embedding"] for item in items]
        except (KeyError, TypeError):
            raise LLMResponseError(PROVIDER, "нет data[].embedding") from None
        if len(vectors) != len(batch):
            raise LLMResponseError(PROVIDER, "число векторов не совпало с числом текстов")
        if any(len(v) != self.dim for v in vectors):
            raise LLMResponseError(
                PROVIDER, f"размерность вектора не равна {self.dim}; проверьте GIGACHAT_EMBEDDINGS_DIM"
            )
        return vectors

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Векторы в том же порядке, что и тексты. Пакеты идут параллельно (с лимитом)."""
        batches = [texts[i : i + self._batch] for i in range(0, len(texts), self._batch)]
        results = await asyncio.gather(*(self._embed_batch(b) for b in batches))
        return [vector for batch in results for vector in batch]


def build_gigachat(
    settings: Settings, http: httpx.AsyncClient
) -> tuple[GigaChatProvider, GigaChatEmbeddings]:
    """Один GigaChatAuth на оба сервиса: токен общий."""
    auth = GigaChatAuth(
        http, settings.gigachat_credentials, settings.gigachat_scope, settings.gigachat_auth_url
    )
    common = {"max_retries": settings.gigachat_max_retries}
    llm = GigaChatProvider(
        http, auth, settings.gigachat_base_url, model=settings.gigachat_model, **common
    )
    embeddings = GigaChatEmbeddings(
        http,
        auth,
        settings.gigachat_base_url,
        model=settings.gigachat_embeddings_model,
        dim=settings.gigachat_embeddings_dim,
        batch_size=settings.gigachat_embeddings_batch,
        concurrency=settings.gigachat_embeddings_concurrency,
        **common,
    )
    return llm, embeddings


def make_ssl_context(settings: Settings) -> ssl.SSLContext:
    """Хранилище certifi + встроенный сертификат российского УЦ (+ GIGACHAT_CA_BUNDLE, если задан).

    Встроенный сертификат есть всегда, поэтому неверный или пустой GIGACHAT_CA_BUNDLE
    не ломает TLS до GigaChat.
    """
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(cadata=RUSSIAN_TRUSTED_CA)
    bundle = settings.gigachat_ca_bundle
    if bundle:
        if os.path.isfile(bundle):
            ctx.load_verify_locations(cafile=bundle)
        else:
            log.warning(
                "GIGACHAT_CA_BUNDLE=%s не найден: используется встроенный сертификат российского УЦ",
                bundle,
            )
    return ctx


def make_http_client(settings: Settings) -> httpx.AsyncClient:
    """Клиент с проверкой TLS, доверяющий российскому УЦ (см. make_ssl_context)."""
    verify: ssl.SSLContext | bool = make_ssl_context(settings)
    if not settings.gigachat_verify_ssl:
        log.warning("GIGACHAT_VERIFY_SSL=false: проверка TLS отключена, только для отладки")
        verify = False
    return httpx.AsyncClient(timeout=settings.llm_timeout_sec, verify=verify)
