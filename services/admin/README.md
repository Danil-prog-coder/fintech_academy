# admin — ядро платформы

Единственный сервис, который видит RAG (`llm`). Наружу отдаёт:

- **открытый API `/v1`** для интеграций (ключ `X-Api-Key`) — контракт в [docs/API.md](../../docs/API.md);
- **сайт** для владельца, админов и поддержки (`frontend/`, React) и его API `/panel/api` (cookie-сессия);
- **вебхук Jira** `/jira/webhook/{project}` и **подписанные ссылки на документы** `/v1/public/rag/documents/…`.

## Запуск

Сервис самостоятельный: свои Postgres и Redis ([docker-compose.yml](docker-compose.yml)), `llm` для старта не нужен —
без него не работают только ответы ИИ и загрузка документации.

```bash
docker compose -f services/admin/docker-compose.yml up -d --build   # из корня репозитория
```

## Код

```
backend/admin_api/
  main.py, cli.py   приложение FastAPI и командная строка (ключи интеграций)
  api/              HTTP: v1 (интеграции), panel (сайт), public (ссылки на документы, вебхук Jira), deps
  services/         логика: accounts, projects, asking, questions, escalations, jira, events, docs, stats,
                    integrations; rag — клиент к llm
  db/               session (движок, сессии), models (таблицы)
  core/             config, security, errors, ratelimit, runtime (общие зависимости приложения)
backend/alembic/    миграции
frontend/           сайт (React, FSD) и его nginx
```

| Путь | Что |
|---|---|
| `backend/admin_api/api/v1.py` | открытый API: проекты, статусы, вопросы (sync / SSE), оценки, обращения, события, вебхук |
| `backend/admin_api/api/panel.py` | API сайта по ролям: документация и разделы, участники, вопросы без ответа, статистика, FAQ, обращения, Jira, код проекта |
| `backend/admin_api/api/public.py` | прокси подписанных ссылок на документы, вебхук Jira |
| `backend/admin_api/services/projects.py` | проекты, коды, участники и правила статусов, вход по коду, ссылки доступа |
| `backend/admin_api/services/accounts.py` | аккаунты сайта: регистрация и вход, выбор проекта, создание проекта, вход админом по коду, привязка доступа по ссылке, лимиты попыток |
| `backend/admin_api/services/asking.py` | вопрос → RAG (разделы участника) → журнал, вопросы админам, обращения |
| `backend/admin_api/services/escalations.py`, `jira.py` | обращения в ТП и их зеркало в Jira (идемпотентное создание, синхронизация, вебхук) |
| `backend/admin_api/services/events.py` | outbox событий: опрос по курсору и вебхуки с подписью HMAC и повторами |
| `backend/admin_api/services/docs.py` | слежение за индексацией → событие `docs.updated` |
| `backend/admin_api/cli.py` | ключи интеграций: `integration-create / rotate / revoke / list` |
| `frontend/` | сайт (React 19, RTK Query, FSD) и nginx, который отдаёт сайт, `/panel/api`, `/v1` и `/jira` с одного домена |

## Запуск без Docker

```bash
cd backend && uv venv -p 3.12 .venv && uv pip install -p .venv -e '.[dev]'
```
```bash
cp .env.example .env    # SECRET_KEY, RAG_URL, RAG_API_TOKEN, BOOTSTRAP_INTEGRATIONS; DATABASE_URL на свой Postgres
```
```bash
.venv/bin/alembic upgrade head && .venv/bin/uvicorn admin_api.main:app_factory --factory --port 8000
```
```bash
cd ../frontend && npm ci && npm run dev    # http://localhost:5173, прокси /panel/api и /v1 → :8000
```

## Тесты

`cd backend && .venv/bin/pytest` — 20 сценариев на SQLite, те же на Postgres: `TEST_DATABASE_URL=postgresql+asyncpg://…`.
RAG, Jira и адреса вебхуков в тестах подменяются на уровне HTTP-транспорта.

## Роли на сайте

| | Статистика, документация, вопросы, участники, FAQ | Обращения в ТП | Настройки (код проекта, Jira) |
|---|---|---|---|
| owner | ✓ | ✓ | ✓ |
| admin | ✓ (участники — только `user`) | ✓ | — |
| support | — | ✓ | — |
