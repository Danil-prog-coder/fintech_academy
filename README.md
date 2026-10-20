# «Решено» (fintech_academy)

AI-помощник по проекту и почтовый клиент в одном приложении.

- **Ассистент.** Пользователь подключает репозиторий GitHub, сервис индексирует его (код, документацию, issues и PR) и отвечает на вопросы с источниками. После каждого коммита индекс обновляется сам. Вопросы можно задавать в чате или кнопкой «Спросить у ИИ» при написании письма.
- **Почта.** Подключение ящиков по IMAP/SMTP, чтение, поиск, перенос и удаление писем, отправка с вложениями, черновики.

Состав: `back-end/` (FastAPI, PostgreSQL + pgvector, worker индексации), `frontend/` (React + Vite), `docs/` (ТЗ). Техническое описание бэкенда: [back-end/TECH_DOC.md](back-end/TECH_DOC.md).

## Запуск

Нужны Docker и Python 3.12 (только для скрипта настройки).

```bash
python back-end/scripts/setup_env.py --fetch-ca
docker compose up --build
```

Первая команда создаёт `back-end/.env`, сама генерирует `SECRET_KEY`, `ENCRYPTION_KEY` и `GITHUB_WEBHOOK_SECRET` и скачивает сертификат российского УЦ для GigaChat в `back-end/certs/`. Если `.env` уже есть, существующие значения не меняются.

Дальше остаётся вставить ключи в `back-end/.env`:

| Переменная | Обязательно | Откуда взять |
|---|---|---|
| `GIGACHAT_CREDENTIALS` | да | Authorization key из кабинета GigaChat ([developers.sber.ru](https://developers.sber.ru/studio)) |
| `YANDEX_API_KEY`, `YANDEX_FOLDER_ID` | нет | Запасная нейросеть YandexGPT: включается сама, если GigaChat недоступен |
| `PUBLIC_BASE_URL` | для автообновления индекса | Публичный адрес сервиса, например `https://resheno.example.com`. GitHub шлёт вебхуки на `PUBLIC_BASE_URL/github/webhook`; на локальном адресе вебхук не создаётся, индекс обновляется переподключением репозитория |

Токен GitHub в настройки сервера не вносится: каждый пользователь вводит его сам при подключении приватного репозитория (нужны права на чтение и `admin:repo_hook`, чтобы сервис мог сам создать вебхук). Пароль ящика пользователь вводит при подключении почты: для Gmail, Яндекса, Mail.ru и iCloud нужен **пароль приложения**, а не основной пароль.

После запуска:

- сайт: http://localhost:3000
- API и Swagger: http://localhost:8000/docs

Без ключей всё поднимается, но чат отвечает «LLM не настроен», а индексация ждёт ключей. Почта от ключей не зависит.

## Что внутри `docker compose`

| Сервис | Назначение |
|---|---|
| `postgres` | PostgreSQL 16 с расширением pgvector |
| `api` | FastAPI; при старте сам применяет миграции |
| `worker` | Индексация репозиториев и обновление по коммитам |
| `frontend` | nginx со сборкой фронтенда; `/api` проксируется на `api` |

## Проверка

```bash
cd back-end
pip install -e ".[dev]"
pytest                      # e2e-сценарии на локальных заглушках GitHub, GigaChat, IMAP и SMTP
ruff check .
E2E_DATABASE_URL=postgresql+asyncpg://... pytest tests/test_e2e_knowledge.py   # то же на настоящем PostgreSQL
```

Живая проверка ключей: `python -m scripts.check_llm` (в Docker: `docker compose exec api python -m scripts.check_llm`).

## Безопасность

- В `back-end/.env.example` раньше лежал настоящий `GIGACHAT_AUTH_KEY`. Он остался в истории git: **отзовите его в кабинете GigaChat** и выпустите новый.
- Для продакшена задайте свои `SECRET_KEY`, `ENCRYPTION_KEY` (иначе у `docker compose` подставляются публичные dev-значения) и `GITHUB_WEBHOOK_SECRET`.
- Токены GitHub и пароли ящиков хранятся только зашифрованными (Fernet). Тексты писем в БД не сохраняются, в журналы не попадают ни тексты вопросов и писем, ни query-строки.
- Если поменять `ENCRYPTION_KEY`, сохранённые токены и пароли ящиков перестанут расшифровываться: пользователям придётся подключить их заново.
