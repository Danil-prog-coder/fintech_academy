FROM python:3.12-slim
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 10001 app
WORKDIR /srv

COPY pyproject.toml ./
COPY mail_api ./mail_api
RUN pip install .
COPY alembic.ini ./
COPY alembic ./alembic

USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4)" || exit 1
# The application writes its own access log (no query strings), so uvicorn's is off.
CMD ["sh", "-c", "alembic upgrade head && uvicorn mail_api.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --no-access-log"]
