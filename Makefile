# Проверки без Docker: у каждого сервиса своё окружение (uv), у сквозного теста — общее.

SERVICES := services/llm services/admin/backend services/mail/backend

.PHONY: test test-llm test-admin test-mail test-e2e check-web lint env deploy

env:
	python3 scripts/setup_env.py

deploy:
	./scripts/deploy.sh

services/llm/.venv:
	cd services/llm && uv venv -q -p 3.12 .venv && uv pip install -q -p .venv -e '.[dev]'

services/admin/backend/.venv:
	cd services/admin/backend && uv venv -q -p 3.12 .venv && uv pip install -q -p .venv -e '.[dev]'

services/mail/backend/.venv:
	cd services/mail/backend && uv venv -q -p 3.12 .venv && uv pip install -q -p .venv -e '.[dev]'

test-llm: services/llm/.venv
	cd services/llm && .venv/bin/pytest -q -p no:cacheprovider

test-admin: services/admin/backend/.venv
	cd services/admin/backend && .venv/bin/pytest -q -p no:cacheprovider

test-mail: services/mail/backend/.venv
	cd services/mail/backend && .venv/bin/pytest -q -p no:cacheprovider

test-e2e:
	$(MAKE) -C tests/e2e test

test: test-llm test-admin test-mail test-e2e

lint: services/admin/backend/.venv services/mail/backend/.venv
	cd services/admin/backend && .venv/bin/ruff check admin_api tests
	cd services/mail/backend && .venv/bin/ruff check mail_api tests

check-web:
	cd services/mail/frontend && npm ci --no-audit --no-fund && npm run check && npm run build
	cd services/admin/frontend && npm ci --no-audit --no-fund && npm run check && npm run build
