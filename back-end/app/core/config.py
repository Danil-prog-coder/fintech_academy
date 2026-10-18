from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    secret_key: str
    encryption_key: str
    access_token_ttl_min: int = 30
    refresh_token_ttl_days: int = 30

    llm_primary: str = "gigachat"
    llm_fallback: str = "yandex"
    embeddings_provider: str = "gigachat"
    llm_timeout_sec: int = 30

    github_webhook_secret: str = ""
    public_base_url: str = "http://localhost:8000"
    max_repo_files: int = 1_000_000
    max_file_bytes: int = 1_000_000_000
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
