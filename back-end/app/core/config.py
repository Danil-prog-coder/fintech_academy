from functools import lru_cache

from pydantic import AliasChoices, Field
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
    # Authorization key (base64 от client_id:client_secret). Имена из .env.example принимаются как алиасы.
    gigachat_credentials: str = Field(
        "", validation_alias=AliasChoices("GIGACHAT_CREDENTIALS", "GIGACHAT_AUTH_KEY")
    )
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat"
    gigachat_embeddings_model: str = "Embeddings"
    gigachat_embeddings_dim: int = 1024
    gigachat_embeddings_batch: int = 32
    gigachat_embeddings_concurrency: int = 3
    # Путь к сертификату российского УЦ.
    gigachat_ca_bundle: str = Field(
        "", validation_alias=AliasChoices("GIGACHAT_CA_BUNDLE", "GIGACHAT_CA_BUNDLE_FILE")
    )
    # false отключает проверку TLS — только для локальной отладки.
    gigachat_verify_ssl: bool = True
    gigachat_auth_url: str = Field(
        "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        validation_alias=AliasChoices("GIGACHAT_AUTH_URL", "GIGACHAT_OAUTH_URL"),
    )
    gigachat_base_url: str = Field(
        "https://gigachat.devices.sberbank.ru/api/v1",
        validation_alias=AliasChoices("GIGACHAT_BASE_URL", "GIGACHAT_API_URL"),
    )
    gigachat_max_retries: int = 2

    github_webhook_secret: str = ""
    public_base_url: str = "http://localhost:8000"
    max_repo_files: int = 1_000_000
    max_file_bytes: int = 1_000_000_000
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
