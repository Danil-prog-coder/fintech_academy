# Открытый API платформы (`/v1`)

Через этот API любая система подключает к себе ответы по документации: почта, мессенджер, портал, CRM.
Платформа хранит проекты, статусы участников, ответы, обращения в поддержку и события, а интегратор
передаёт **свои** идентификаторы пользователей. Демо-почта (`services/mail`) — пример такой интеграции.

Полная схема — Swagger на `/docs` и `/openapi.json` сервиса admin.

## Общее

| | |
|---|---|
| Адрес | `https://<домен платформы>/v1/…` (в compose — `http://localhost:3001/v1`) |
| Авторизация | заголовок `X-Api-Key: <ключ интеграции>` |
| Формат | JSON, UTF-8 |
| Ошибки | `{"code": "...", "message": "...", "retryable": true|false}`, сообщения на русском |
| Лимит | `API_RATE_PER_MINUTE` запросов в минуту на ключ (по умолчанию 600), сверх — `429` + `Retry-After` |

**Ключ интеграции** выдаёт оператор платформы: `python -m admin_api.cli integration-create <slug> "<Название>"`
(ключ показывается один раз; `integration-rotate` выпускает новый, `integration-revoke` отзывает).
Чужие проекты для ключа неотличимы от несуществующих (`404 project_not_found`).

**Пользователь** — это `external_id`: id пользователя в системе интегратора (до 128 символов: буквы, цифры,
`. _ @ : + -`). Платформа не хранит о нём ничего, кроме id, статуса и необязательного имени. Сама она не может
проверить, кто стоит за id, — это делает интегратор (так же, как Telegram-бот в Innopolis отвечал за Telegram id).

## Статусы и правила

| Статус | Что может | Сайт администратора |
|---|---|---|
| `owner` | всё: назначать `admin` / `support` / `user`, удалять любого, Jira, код проекта | да |
| `admin` | документация, пользователи (`user`), вопросы без ответа, статистика, обращения | да |
| `support` | обращения в поддержку (ТП) | да |
| `user` | задавать вопросы, писать в поддержку | нет |

Правила проверяет платформа, а не интегратор: владелец задаётся при создании проекта и не меняется; админ
управляет только пользователями; никто не меняет свой статус. Для `owner`, `admin` и `support` создаётся вход
на сайт (логин + пароль + **код проекта**). Пароль через API не передаётся: в ответе приходит одноразовая ссылка
`…/setup?token=…` (72 часа), по которой человек задаёт пароль сам.

## Проекты

### `POST /v1/projects` — создать проект

```json
{"name": "Отдел кадров", "owner_external_id": "u-42", "owner_login": "hr-owner", "owner_display_name": "Ольга"}
```
→ `201`
```json
{"project": {"id": "1f3a9c0b", "name": "Отдел кадров", "role": "owner", "created_at": "…"},
 "project_code": "1f3a9c0b-Zq…",
 "owner_panel_setup_url": "https://…/setup?token=…"}
```
`project_code` показывается **один раз** (владелец видит его потом на сайте в «Настройках»). Покажите его
создателю сразу — например, во всплывающем окне, которое не остаётся в истории.

### `GET /v1/projects?external_id=u-42` — проекты пользователя (с его статусом)
Без `external_id` — все проекты интеграции (`limit`, `offset`).

### `GET /v1/projects/{id}`, `GET /v1/projects/{id}/sections`
Разделы документации проекта (`general` — «Общее» — есть всегда).

## Участники

### `PUT /v1/projects/{id}/members/{external_id}` — назначить статус

```json
{"acting_external_id": "u-42", "role": "support", "login": "anna-support",
 "display_name": "Анна", "allowed_sections": ["general"]}
```
- `acting_external_id` — кто выполняет действие (владелец или админ проекта);
- `login` обязателен, когда человек впервые получает `admin` или `support`;
- `allowed_sections` — разделы, которые видит `user` / `support` (`null` — все). Не передан — не меняется
  (`keep_sections: false` — сбросить на «все»). Владелец и админы видят всё всегда.

→ `{"member": {...}, "panel_setup_url": "…"}` (ссылка — только если создан вход на сайт). Понижение до
`user` удаляет вход на сайт и закрывает его сессии.

### Прочее
| Метод | Путь | |
|---|---|---|
| GET | `/v1/projects/{id}/members?role=` | список |
| GET | `/v1/projects/{id}/members/{external_id}` | один участник |
| DELETE | `/v1/projects/{id}/members/{external_id}?acting_external_id=` | удалить (`204`) |
| POST | `/v1/projects/{id}/members/{external_id}/panel-password-reset` `{"acting_external_id"}` | новая ссылка для пароля: себе или владельцем — любому |

## Вопросы

### `POST /v1/projects/{id}/ask`

```json
{"external_id": "u-7", "message": "Как оформить отпуск?", "channel": "telegram", "stream": false,
 "images": [{"mime": "image/png", "data_base64": "…"}]}
```
- пользователь должен состоять в проекте (`403 not_a_member`);
- поиск идёт только по разделам, открытым этому участнику;
- память диалога ведётся на платформе по паре проект + `external_id` (сбросить — `POST …/members/{external_id}/reset-dialog`);
- картинки (скриншот ошибки) — до 3 штук, png/jpeg/webp/gif до 5 МБ.

Ответ (`stream: false`):
```json
{"request_id": "ef1fd71c6c414894",
 "action": "answer",
 "text": "Заявление оформляется в кадровом портале [1].",
 "formatted_text": "…текст + блок «Источники»…",
 "sources": [{"citation_label": "[1]", "document_title": "Регламент отпусков",
              "section_path": "Регламент отпусков → 1 Оформление отпуска",
              "excerpt": "Заявление на отпуск оформляется в кадровом портале", "url": "https://…/v1/public/rag/documents/…?sig=…"}],
 "images": [{"id": "vacation/img001.png", "url": "https://…/v1/projects/{id}/images/vacation/img001.png"}],
 "confidence": 0.82, "confidence_level": "high", "buttons": [], "cache_hit": false, "latency_ms": 5400}
```

`action`:
| | Что значит | Что делает платформа |
|---|---|---|
| `answer` | ответ по документации, каждое утверждение с цитатой | — |
| `clarify` | нужен уточняющий вопрос | — |
| `offer_operator` | в документации ответа нет | вопрос уходит владельцу и админам (`question_id` в ответе); кнопка «Связаться с поддержкой» |
| `escalate` | пользователь попросил человека | сразу открывается обращение (`escalation: {key, status}`) |

`stream: true` — Server-Sent Events: `status` («Ищу в документации…»), `delta` (проверенные абзацы по мере
генерации), `reset` (убрать показанный текст), один `final` — тот же объект, что и синхронный ответ;
`error` — если сервис ответов недоступен.

`url` источника открывается без ключа: ссылка подписана и ведёт только на этот документ.
Картинки — `GET /v1/projects/{id}/images/{image_id}` с ключом (`?crop=true` — фрагмент в рамке).

### Прочее
| Метод | Путь | |
|---|---|---|
| POST | `/v1/projects/{id}/feedback` `{"external_id", "request_id", "value": 1 \| -1, "comment"}` | оценка; `-1` отправляет вопрос админам |
| GET | `/v1/projects/{id}/faq/popular?limit=5` | частые вопросы — для меню / приветствия |

## Обращения в поддержку (ТП)

| Метод | Путь | |
|---|---|---|
| POST | `/v1/projects/{id}/escalations` `{"external_id", "message", "request_id"}` | открыть (одно открытое на человека: повторный вызов вернёт его) |
| GET | `/v1/projects/{id}/escalations?external_id=&status=open` | обращения пользователя |
| GET | `/v1/projects/{id}/escalations/{key}?external_id=` | с перепиской (внутренние заметки ТП не показываются) |
| POST | `/v1/projects/{id}/escalations/{key}/messages` `{"external_id", "text"}` | сообщение пользователя |
| POST | `/v1/projects/{id}/escalations/{key}/rating` `{"external_id", "value"}` | оценка после закрытия |

Если у проекта настроена Jira, обращение становится задачей в Jira, а переписка — комментариями.

## События

Ответы, которые появляются позже (админ ответил на вопрос, поддержка написала, вышла новая версия
документации), приходят событиями. Один журнал, два способа чтения:

**Опрос** — работает без публичного адреса:
```
GET /v1/events?after=<id последнего обработанного>&limit=100
→ {"events": [{"id": 17, "event_id": "uuid", "type": "question.answered", "project_id": "1f3a9c0b",
               "created_at": "…", "data": {…}}], "next_after": 17}
```

**Вебхук** — `PUT /v1/integration/webhook {"url": "https://…"}` → `{"url", "secret"}` (секрет показывается один раз).
Платформа шлёт `POST` с заголовками `X-Platform-Event`, `X-Platform-Event-Id` и
`X-Platform-Signature: t=<unix>,v1=<hex>`, где `hex = HMAC-SHA256(secret, "<t>.<тело>")`. Проверяйте подпись и
отбрасывайте `t` старше 5 минут. Ответ не `2xx` — повтор с нарастающей паузой (до `WEBHOOK_MAX_ATTEMPTS`).
Адрес — только `https` и не во внутреннюю сеть (для разработки — `WEBHOOK_ALLOW_PRIVATE=true`).

Доставка «как минимум один раз»: дедуплицируйте по `event_id`.

| `type` | `data` |
|---|---|
| `question.answered` | `external_id`, `question`, `answer`, `question_id`, `request_id` |
| `escalation.created` | `key`, `external_id`, `status`, `reason` |
| `escalation.message` | `key`, `external_id`, `text`, `author: "support"`, `author_name`, `message_id` |
| `escalation.status_changed` | `key`, `external_id`, `status` (`waiting` / `in_progress` / `waiting_customer` / `resolved` / `closed`) |
| `docs.updated` | `kind`, `summary`, `generation`, `counts` — разошлите участникам проекта (`GET …/members`) |

## Пример: подключение за 5 запросов

```bash
KEY=ik_my-bot_…; API=https://platform.example.com/v1
# 1. проект от имени пользователя 42 вашей системы
curl -s -X POST $API/projects -H "X-Api-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"name":"Отдел кадров","owner_external_id":"42","owner_login":"hr-owner"}'
# 2. коллега 77 — пользователь проекта
curl -s -X PUT $API/projects/1f3a9c0b/members/77 -H "X-Api-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"acting_external_id":"42","role":"user"}'
# 3. вопрос
curl -s -X POST $API/projects/1f3a9c0b/ask -H "X-Api-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"external_id":"77","message":"Как оформить отпуск?"}'
# 4. события (ответы админов и поддержки)
curl -s "$API/events?after=0" -H "X-Api-Key: $KEY"
```
Документацию владелец загружает на сайте администратора (ссылка для пароля пришла в шаге 1).
