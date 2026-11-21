# admin — ядро платформы

Единственный сервис, который видит RAG (`llm`). Наружу отдаёт:

- **открытый API `/v1`** для интеграций (ключ `X-Api-Key`) — контракт в [docs/API.md](../../docs/API.md);
- **сайт** для владельца, админов и поддержки (`frontend/`, React) и его API `/panel/api` (cookie-сессия);
- **вебхук Jira** `/jira/webhook/{project}` и **подписанные ссылки на документы** `/v1/public/rag/documents/…`.

## Код

| Путь | Что |
|---|---|
| `backend/admin_api/api/v1.py` | открытый API: проекты, статусы, вопросы (sync / SSE), оценки, обращения, события, вебхук |
| `backend/admin_api/api/panel.py` | API сайта по ролям: документация и разделы, участники, вопросы без ответа, статистика, FAQ, обращения, Jira, код проекта |
| `backend/admin_api/api/public.py` | прокси подписанных ссылок на документы, вебхук Jira |
| `backend/admin_api/services/projects.py` | проекты, коды, участники и правила статусов, ссылки для пароля |
| `backend/admin_api/services/accounts.py` | вход: логин + пароль + код проекта, сессии, лимит попыток |
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
