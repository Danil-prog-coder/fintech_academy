"""Показывает сырой ответ GigaChat на потоковый запрос (статус, заголовки, первые строки).

Запуск: docker compose exec api python -m scripts.debug_stream
Тратит один маленький запрос к чату. Токены и ключ не печатаются.
"""

import asyncio
import uuid

import httpx

from app.core.config import get_settings
from app.llm.gigachat import GigaChatAuth, make_http_client


async def main() -> None:
    s = get_settings()
    async with make_http_client(s) as http:
        auth = GigaChatAuth(http, s.gigachat_credentials, s.gigachat_scope, s.gigachat_auth_url)
        # Сначала сырой запрос токена: GigaChatAuth прячет причину ошибки.
        try:
            r = await http.post(
                s.gigachat_auth_url,
                headers={
                    "Authorization": f"Basic {auth._key}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={"scope": s.gigachat_scope},
            )
        except httpx.HTTPError as e:
            raise SystemExit(f"авторизация: сетевая/TLS ошибка {type(e).__name__}: {e!r}") from None
        print("auth status:", r.status_code)
        if r.status_code != 200:
            raise SystemExit(f"авторизация: тело ответа {r.text[:300]!r}")
        token = r.json()["access_token"]
        payload = {
            "model": s.gigachat_model,
            "messages": [{"role": "user", "content": "Посчитай до трёх"}],
            "stream": True,
            "max_tokens": 40,
        }
        async with http.stream(
            "POST",
            f"{s.gigachat_base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        ) as r:
            print("status:", r.status_code)
            print("content-type:", r.headers.get("content-type"))
            n = 0
            async for line in r.aiter_lines():
                print(f"{n:02d} {line!r}")
                n += 1
                if n >= 20:
                    print("... (обрезано)")
                    break
            print("строк всего (до обрезки):", n)


if __name__ == "__main__":
    asyncio.run(main())
