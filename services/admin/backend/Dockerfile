FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY admin_api ./admin_api
RUN pip install .
COPY alembic.ini ./
COPY alembic ./alembic
RUN useradd --system --uid 10010 app
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4)" || exit 1
# migrations first: the schema changes only through Alembic
CMD ["sh", "-c", "alembic upgrade head && uvicorn admin_api.main:app_factory --factory --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
