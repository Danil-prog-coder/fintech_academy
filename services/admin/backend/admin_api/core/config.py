"""Settings of the admin service. Fail-fast: missing secrets stop the process at start, not at the first request."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://admin:admin@localhost:5432/admin"
    redis_url: str = ""  # empty — rate limits are kept per process

    # Secret material. SECRET_KEY derives the Fernet key that encrypts project codes, Jira tokens and webhook secrets.
    secret_key: str = Field(min_length=32)

    # The hidden RAG service (internal network only)
    rag_url: str = "http://llm:8080"
    rag_api_token: str = ""
    rag_timeout_s: float = 120.0

    # Public addresses: the site (links to set a password) and this API (document links of answers)
    panel_public_url: str = "http://localhost:3001"
    api_public_url: str = "http://localhost:8000"

    # Integrations created at start-up: "slug:Name:key;slug2:Name2:key2" (keys ≥ 32 chars). Others — via the CLI.
    bootstrap_integrations: str = ""
    # Projects created on the site belong to this integration (its users ask the questions); empty — the oldest one
    site_projects_integration: str = ""

    # Panel sessions and password links
    session_ttl_hours: int = 12
    setup_link_ttl_hours: int = 72
    cookie_secure: bool = False  # true behind HTTPS
    login_attempts: int = 10
    login_window_s: int = 900

    # Integration API rate limit: requests per minute per integration key
    api_rate_per_minute: int = 600

    # Outgoing webhooks
    webhook_allow_private: bool = False  # allow http(s)://10.x / docker hosts (dev, compose)
    webhook_timeout_s: float = 10.0
    webhook_max_attempts: int = 10
    worker_interval_s: float = 2.0
    workers_enabled: bool = True

    # Jira (per-project settings live in the database; this is only the worker cadence)
    jira_timeout_s: float = 20.0
    jira_max_attempts: int = 8

    # CORS for the site in dev (comma-separated origins); production serves the site from the same origin
    cors_origins: str = ""

    log_level: str = "INFO"

    @field_validator("secret_key")
    @classmethod
    def _no_placeholder(cls, v: str) -> str:
        if v.startswith("<") or v.lower().startswith("change"):
            raise ValueError("SECRET_KEY is a placeholder: generate one (python -c 'import secrets;print(secrets.token_urlsafe(48))')")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
