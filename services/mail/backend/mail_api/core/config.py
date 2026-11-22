"""Settings of the mail demo: a mail client (IMAP/SMTP) with its own users that integrates the platform."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    secret_key: str
    encryption_key: str
    access_token_ttl_min: int = 30
    refresh_token_ttl_days: int = 30
    log_level: str = "INFO"

    # The platform (admin service, open API /v1). The demo is an ordinary integration with its own key.
    platform_url: str = "http://admin:8000"
    platform_api_key: str = ""
    platform_timeout_sec: float = 120.0
    # Events (answers of admins, support replies) are read by polling the platform: the demo needs no public URL
    events_poll_sec: float = 5.0
    events_enabled: bool = True

    # Rate limits (per process)
    rate_limit_enabled: bool = True

    # Mail client (IMAP/SMTP). Mailbox passwords are stored encrypted only.
    mail_timeout_sec: int = 20
    # Allow private / local mail hosts. Development and tests only: otherwise a user could make the server
    # reach the internal network (SSRF).
    mail_allow_private_hosts: bool = False
    mail_max_send_bytes: int = 25 * 1024 * 1024
    mail_max_attachment_bytes: int = 25 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
