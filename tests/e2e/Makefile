# Сквозной тест трёх сервисов в одном процессе (без Docker, сети и ключей моделей).
VENV := .venv
PY := $(VENV)/bin/python

$(PY):
	uv venv -q -p 3.12 $(VENV)
	uv pip install -q -p $(VENV) -e ../../services/llm -e '../../services/admin/backend[dev]' -e '../../services/mail/backend[dev]'

test: $(PY)
	$(VENV)/bin/pytest -q -p no:cacheprovider .

.PHONY: test
