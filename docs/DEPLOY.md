# Запуск на сервере (Timeweb Cloud и любой VPS)

Нужны сервер на Ubuntu 22.04/24.04 и домен. HTTPS настраивается сам: в `docker-compose.yml` есть сервис `caddy`,
он выпускает и продлевает сертификаты Let's Encrypt. Ставить на сервер nginx и certbot не нужно.

## 1. Сервер

| | Минимум (демо) | Рекомендуется |
|---|---|---|
| CPU | 2 vCPU | 4 vCPU |
| RAM | 4 ГБ + swap | 8 ГБ |
| Диск | 40 ГБ NVMe | 60–80 ГБ NVMe |
| ОС | Ubuntu 24.04 | Ubuntu 24.04 |

В панели Timeweb: «Облачные серверы» → «Создать» → Ubuntu 24.04 → конфигурация → в поле **Cloud-init**
вставьте [`deploy/cloud-init.yaml`](../deploy/cloud-init.yaml), заменив в нём SSH-ключ на свой. Он ставит
Docker, включает swap 4 ГБ, файрвол (открыты только 22, 80, 443), ограничивает размер логов и создаёт
пользователя `deploy`. Без cloud-init то же самое можно сделать руками командами из этого файла.

## 2. DNS

У регистратора домена (или в Timeweb: «Домены и SSL» → DNS) создайте две A-записи на IP сервера:

```
platform.example.com   A   <IP сервера>     # сайт администратора и открытый API /v1
mail.example.com       A   <IP сервера>     # демо-почта (можно не делать, если демо не нужно)
```

Записи должны начать работать до первого запуска, иначе Let's Encrypt не выдаст сертификат
(проверка: `getent hosts platform.example.com`).

## 3. Код и секреты

```bash
ssh deploy@<IP сервера>
```
```bash
git clone https://github.com/danil-prog-coder/fintech_academy.git && cd fintech_academy
```

Репозиторий приватный: для клонирования нужен [deploy key](https://docs.github.com/ru/authentication/connecting-to-github-with-ssh/managing-deploy-keys)
(`ssh-keygen -t ed25519` на сервере, публичную часть — в Settings → Deploy keys репозитория, клонировать по `git@github.com:...`)
или personal access token с доступом на чтение.

```bash
python3 scripts/setup_env.py --domain platform.example.com --mail-domain mail.example.com --email you@example.com
```

Скрипт создаёт `services/*/.env` с согласованными секретами, корневой `.env` (профиль `https` и пароли баз)
и `deploy/Caddyfile`. `--email` необязателен: на него Let's Encrypt пишет, если с сертификатом что-то не так.

```bash
nano services/llm/.env        # вписать OPENROUTER_API_KEY
```

## 4. Запуск

```bash
./scripts/deploy.sh
```

Скрипт проверяет Docker, `.env`, ключ модели, DNS, память и диск, затем собирает и поднимает контейнеры
(первый раз 5–10 минут), ждёт, пока платформа станет здоровой, и печатает адреса. Сертификат выпускается
за несколько секунд при первом обращении к домену.

Дальше: `https://platform.example.com` — сайт администратора и API (`/docs` — Swagger),
`https://mail.example.com` — демо-почта: регистрация → «Проекты» → создать проект.

## Обновление

```bash
./scripts/deploy.sh           # git pull + пересборка + перезапуск; данные в томах сохраняются
```

## Если что-то не так

| Симптом | Что смотреть |
|---|---|
| Браузер пишет про сертификат | `docker compose logs caddy`: чаще всего A-запись ещё не указывает на сервер или закрыт порт 80 |
| Сайт открывается, но вопросы не отвечаются | `OPENROUTER_API_KEY` в `services/llm/.env`, затем `docker compose restart llm`; `docker compose logs llm` |
| Сборка падает с `Killed` | мало памяти: нужен swap (есть в `cloud-init.yaml`) |
| `password authentication failed` в логах баз | тома баз созданы раньше со старыми паролями (например, до `setup_env.py --domain`): на свежем сервере — `docker compose down -v` и запуск заново; если данные нужны — верните прежние пароли в корневой `.env` |
| Кончилось место | `docker builder prune -af && docker image prune -af` |
| Сменить домен | снова `setup_env.py --domain ...` (секреты не меняются), затем `./scripts/deploy.sh --no-pull` |

Полезное: `docker compose ps` — состояние, `docker compose logs -f admin llm` — логи,
`docker compose down` — остановить (данные остаются в томах; `down -v` удалит и их).

Сервер без домена (только посмотреть по IP): `python3 scripts/setup_env.py`, в корневой `.env` добавьте
`PUBLISH_IP=0.0.0.0`, откройте порты (`ufw allow 3000,3001/tcp`) и запустите `./scripts/deploy.sh`.
Сайты будут на `http://<IP>:3001` и `http://<IP>:3000` без шифрования — для работы так не оставляйте.
