#!/usr/bin/env bash
# Запуск и обновление платформы на сервере одной командой:  ./scripts/deploy.sh
# Проверяет, что всё готово (Docker, .env, ключ модели, DNS, память), собирает и поднимает контейнеры,
# ждёт, пока admin станет здоровым, и печатает адреса. Повторный запуск = обновление (git pull + пересборка).
set -euo pipefail
cd "$(dirname "$0")/.."
# весь скрипт в { }: bash дочитывает его целиком до запуска, и git pull посреди работы ему не мешает
{

red() { printf '\033[31m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
die() { red "✗ $*"; exit 1; }

command -v docker >/dev/null || die "нет Docker: curl -fsSL https://get.docker.com | sh"
docker compose version >/dev/null 2>&1 || die "нет docker compose v2 (плагин docker-compose-plugin)"
docker info >/dev/null 2>&1 || die "нет доступа к Docker: запустите через sudo или добавьте пользователя в группу docker"

for f in services/llm/.env services/admin/backend/.env services/mail/backend/.env; do
  [ -f "$f" ] || die "нет $f — сначала: python3 scripts/setup_env.py --domain <домен админки> --mail-domain <домен почты>"
done

key=$(grep -E '^OPENROUTER_API_KEY=' services/llm/.env | cut -d= -f2- | tr -d '"'"'"' ' || true)
case "$key" in ""|"<"*) key="" ;; esac
[ -n "$key" ] || yellow "! OPENROUTER_API_KEY в services/llm/.env пуст: сайт поднимется, но отвечать на вопросы и индексировать документы не будет"

if [ "${1:-}" != "--no-pull" ] && [ -d .git ]; then
  git pull --ff-only || yellow "! git pull не прошёл, собираю то, что есть"
fi

https=0
grep -qsE '^COMPOSE_PROFILES=.*https' .env && https=1
if [ "$https" = 1 ]; then
  [ -f deploy/Caddyfile ] || die "профиль https включён, но нет deploy/Caddyfile — повторите scripts/setup_env.py --domain ..."
  domains=$(grep -E '^[a-z0-9.-]+\.[a-z]{2,} \{' deploy/Caddyfile | cut -d' ' -f1)
  my_ips=$({ ip -4 -o addr show scope global 2>/dev/null || true; } | awk '{print $4}' | cut -d/ -f1)
  for d in $domains; do
    resolved=$({ getent ahostsv4 "$d" || true; } | awk '{print $1}' | sort -u | tr '\n' ' ')
    if [ -z "$resolved" ]; then
      yellow "! $d не резолвится: добавьте A-запись на IP этого сервера, иначе сертификат не выпустится"
    elif [ -n "$my_ips" ] && ! grep -qwF -f <(echo "$my_ips") <<<"$resolved"; then
      yellow "! $d указывает на $resolved, а у сервера адреса: $(echo $my_ips). Если сервер за NAT — это нормально, иначе поправьте A-запись"
    fi
  done
fi

mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
swap_mb=$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$mem_mb" -lt 6000 ] && [ "$swap_mb" -lt 1000 ]; then
  yellow "! памяти ${mem_mb} МБ и нет swap: сборка фронтендов может упасть. Добавьте swap (см. deploy/cloud-init.yaml)"
fi
free_gb=$(df -Pk . | awk 'NR==2 {print int($4/1024/1024)}')
[ "$free_gb" -ge 8 ] || yellow "! свободно ${free_gb} ГБ диска: для сборки нужно ~8 ГБ (docker builder prune -af освобождает кэш)"

green "→ сборка и запуск (первый раз 5–10 минут)"
docker compose up -d --build --remove-orphans

printf '→ жду admin'
for _ in $(seq 1 60); do
  state=$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q admin)" 2>/dev/null || echo starting)
  [ "$state" = healthy ] && break
  printf '.'; sleep 5
done
echo
[ "${state:-}" = healthy ] || { docker compose ps; die "admin не стал здоровым за 5 минут: docker compose logs admin llm"; }

docker image prune -f >/dev/null || true
green "✓ платформа работает"
if [ "$https" = 1 ]; then
  for d in $domains; do echo "  https://$d"; done
  echo "  (сертификат выпускается при первом заходе на домен; ошибки — docker compose logs caddy)"
else
  echo "  админка и API: http://localhost:${ADMIN_PORT:-3001}   почта (демо): http://localhost:${MAIL_PORT:-3000}"
fi
exit 0
}
