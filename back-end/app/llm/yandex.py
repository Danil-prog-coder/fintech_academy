"""Адаптер YandexGPT (запасной провайдер): Foundation Models completion API.

Авторизация — API-ключ в заголовке, каталог (folder id) входит в идентификатор модели.
Формат запросов написан по публичной документации и проверен тестами на заглушках;
на живых ключах его стоит сверить (`python -m scripts.check_llm`).
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.core.config import Settings
from app.llm.base import (
    LLMAuthError,
    LLMResponseError,
    LLMResult,
    LLMUnavailableError,
    Message,
)

log = logging.getLogger(__name__)
PROVIDER = "yandex"


class YandexProvider:
    name = PROVIDER

    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        folder_id: str,
        model: str,
        base_url: str,
        *,
        max_retries: int = 2,
        backoff_sec: float = 0.5,
    ):
        self._http = http
        self._headers = {"Authorization": f"Api-Key {api_key}", "x-folder-id": folder_id}
        self._model_uri = f"gpt://{folder_id}/{model}"
        self._url = f"{base_url.rstrip('/')}/completion"
        self._retries, self._backoff = max_retries, backoff_sec

    def _payload(
        self,
        messages: list[Message],
        *,
        stream: bool,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict:
        options: dict = {"stream": stream}
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["maxTokens"] = str(max_tokens)
        return {
            "modelUri": self._model_uri,
            "completionOptions": options,
            "messages": [{"role": m.role, "text": m.content} for m in messages],
        }

    @staticmethod
    def _raise_for(status: int) -> None:
        if status in (401, 403):
            raise LLMAuthError(PROVIDER)
        if status == 429 or status >= 500:
            raise LLMUnavailableError(PROVIDER)
        if status >= 400:
            raise LLMResponseError(PROVIDER, f"код {status}")

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        payload = self._payload(
            messages, stream=False, temperature=temperature, max_tokens=max_tokens
        )
        attempt = 0
        while True:
            try:
                r = await self._http.post(self._url, json=payload, headers=self._headers)
                status = r.status_code
            except httpx.HTTPError:
                status = None
            if status is None or status == 429 or status >= 500:
                if attempt >= self._retries:
                    raise LLMUnavailableError(PROVIDER)
                await asyncio.sleep(self._backoff * (2**attempt))
                attempt += 1
                continue
            self._raise_for(status)
            break
        try:
            result = r.json()["result"]
            text = result["alternatives"][0]["message"]["text"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMResponseError(PROVIDER, "нет result.alternatives[0].message.text") from None
        usage = result.get("usage") or {}

        def _int(value) -> int | None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        return LLMResult(
            text=text,
            provider=PROVIDER,
            model=self._model_uri,
            prompt_tokens=_int(usage.get("inputTextTokens")),
            completion_tokens=_int(usage.get("completionTokens")),
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Yandex присылает JSON-строки с накопленным текстом; отдаём только прирост."""
        payload = self._payload(messages, stream=True, temperature=temperature, max_tokens=max_tokens)
        sent = ""
        try:
            async with self._http.stream(
                "POST", self._url, json=payload, headers=self._headers
            ) as r:
                self._raise_for(r.status_code)
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        text = json.loads(line)["result"]["alternatives"][0]["message"]["text"]
                    except (ValueError, KeyError, IndexError, TypeError):
                        continue
                    if text.startswith(sent) and len(text) > len(sent):
                        delta, sent = text[len(sent) :], text
                        yield delta
        except httpx.HTTPError:
            raise LLMUnavailableError(PROVIDER) from None


def build_yandex(settings: Settings, http: httpx.AsyncClient) -> YandexProvider | None:
    if not (settings.yandex_api_key and settings.yandex_folder_id):
        return None
    return YandexProvider(
        http,
        settings.yandex_api_key,
        settings.yandex_folder_id,
        settings.yandex_model,
        settings.yandex_base_url,
    )
