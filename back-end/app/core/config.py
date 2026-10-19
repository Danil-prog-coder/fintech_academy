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

    # GigaChat. Без credentials приложение стартует, а LLM-эндпоинты отвечают 503.
    gigachat_credentials: str = ""  # Authorization key (base64 от client_id:client_secret)
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat"
    gigachat_embeddings_model: str = "Embeddings"
    gigachat_embeddings_dim: int = 1024
    gigachat_embeddings_batch: int = 32
    gigachat_embeddings_concurrency: int = 3
    gigachat_ca_bundle: str = ""  # путь к сертификату российского УЦ; TLS не отключаем
    gigachat_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_base_url: str = "https://gigachat.devices.sberbank.ru/api/v1"
    gigachat_max_retries: int = 2

    github_webhook_secret: str = ""
    public_base_url: str = "http://localhost:8000"
    max_repo_files: int = 1_000_000
    max_file_bytes: int = 1_000_000_000
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
