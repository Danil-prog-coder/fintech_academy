"""Дымовой прогон запущенного стека по HTTP, как это делает фронтенд.

По умолчанию репозиторий НЕ подключается и GigaChat не вызывается.
Запуск (стек поднят через docker compose up):
    docker compose exec api python -m scripts.smoke_api
    docker compose exec api python -m scripts.smoke_api --repo https://github.com/<свой>/<репо>
Через фронтовый прокси nginx:
    docker compose exec api python -m scripts.smoke_api --base http://frontend/api
"""

import argparse
import json
import sys
import time
import uuid

import httpx

ASKABLE = {"ready", "updating", "reauth_required"}
problems: list[str] = []


def step(name: str, r: httpx.Response, expected: int) -> dict:
    body: dict = {}
    try:
        body = r.json() if r.content else {}
    except json.JSONDecodeError:
        pass
    if r.status_code == expected:
        print(f"  [OK]   {name}: {r.status_code}")
    else:
        detail = body.get("code") or body.get("detail") or r.text[:200]
        print(f"  [FAIL] {name}: {r.status_code}, ожидали {expected} — {detail}")
        problems.append(name)
    return body


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--repo", help="URL репозитория GitHub для подключения (тратит лимит LLM)")
    p.add_argument("--wait", type=int, default=120, help="сколько секунд ждать индексацию")
    p.add_argument("--question", default="Что делает этот проект?")
    args = p.parse_args()

    with httpx.Client(base_url=args.base, timeout=60) as c:
        print(f"Стек: {args.base}")
        step("GET /health", c.get("/health"), 200)

        email, password = f"smoke-{uuid.uuid4().hex[:8]}@example.com", uuid.uuid4().hex
        tokens = step(
            "POST /auth/register",
            c.post("/auth/register", json={"email": email, "password": password}),
            201,
        )
        step("POST /auth/login", c.post("/auth/login", json={"email": email, "password": password}), 200)
        if "access_token" not in tokens:
            sys.exit("Регистрация не удалась, дальше проверять нечего")
        c.headers["Authorization"] = f"Bearer {tokens['access_token']}"

        step("GET /me", c.get("/me"), 200)
        st = step("GET /repo/status", c.get("/repo/status"), 200)
        print(f"         статус репозитория: {st.get('status')}")
        r = c.post("/qa/ask", json={"question": "тест"})
        step("POST /qa/ask без репозитория → 409", r, 409)

        if args.repo:
            st = step("POST /repo/connect", c.post("/repo/connect", json={"url": args.repo}), 201)
            deadline = time.monotonic() + args.wait
            while st.get("status") not in ASKABLE | {"error"} and time.monotonic() < deadline:
                time.sleep(5)
                st = c.get("/repo/status").json()
                print(f"         индексация: {st.get('status')}")
            if st.get("status") in ASKABLE:
                body = step("POST /qa/ask", c.post("/qa/ask", json={"question": args.question}), 200)
                print(f"         провайдер: {body.get('provider')}, статус: {body.get('status')}")
                print(f"         ответ: {str(body.get('answer'))[:300]!r}")
                print(f"         источников: {len(body.get('sources') or [])}")
            else:
                print(f"  [FAIL] индекс не готов за {args.wait} с: {st.get('status')}")
                problems.append("индексация")
            step("DELETE /repo", c.delete("/repo"), 204)

    print()
    if problems:
        print(f"Не прошло: {', '.join(problems)}")
        sys.exit(1)
    print("Всё в порядке")


if __name__ == "__main__":
    main()
