"""Проверка окружения перед запуском: переменные, сертификат, TLS до GigaChat.

Не тратит лимит GigaChat: ключ никуда не отправляется, только TLS-рукопожатие.
Секреты не печатаются. Запуск из back-end/ (или в контейнере api):
    python -m scripts.check_env
"""

import base64
import binascii
import hashlib
import socket
import ssl
import sys
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from app.core.config import Settings
from app.llm.gigachat import make_ssl_context

# sha256 ключа, который попал в историю git (коммит до 437c631). Его нужно отозвать.
LEAKED_KEY_SHA256 = "ed58c60cb955f164543965ffd2c84ab6945c7fd8e0e9d4a4f57e309ba643f2e8"

problems: list[str] = []


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    problems.append(msg)


def check_settings() -> Settings | None:
    print("1. Переменные окружения")
    try:
        settings = Settings()
    except ValidationError as e:
        for err in e.errors():
            fail(f"{'.'.join(map(str, err['loc'])).upper()}: {err['msg']}")
        return None
    ok(f"DATABASE_URL задан (схема {urlsplit(settings.database_url).scheme})")
    if settings.secret_key in ("change-me", "dev-secret-change-me"):
        warn("SECRET_KEY стандартный — для прода замените")
    else:
        ok("SECRET_KEY задан")
    try:
        if len(base64.urlsafe_b64decode(settings.encryption_key)) != 32:
            raise ValueError
        ok("ENCRYPTION_KEY — корректный Fernet-ключ")
    except (ValueError, binascii.Error):
        fail("ENCRYPTION_KEY не Fernet-ключ (32 байта в urlsafe base64)")
    return settings


def check_key(settings: Settings) -> None:
    print("2. Ключ GigaChat (GIGACHAT_CREDENTIALS / GIGACHAT_AUTH_KEY)")
    key = settings.gigachat_credentials.strip().removeprefix("Basic ").strip()
    if not key:
        fail("ключ не задан — LLM-эндпоинты будут отвечать 503")
        return
    if hashlib.sha256(key.encode()).hexdigest() == LEAKED_KEY_SHA256:
        fail("это СТАРЫЙ ключ из истории git — отзовите его и выпустите новый")
    try:
        decoded = base64.b64decode(key, validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        fail("ключ не base64 — нужен Authorization key из кабинета, а не client_secret")
        return
    if ":" not in decoded:
        fail("ключ не похож на base64(client_id:client_secret)")
        return
    ok(f"формат ключа верный, длина {len(key)}, scope {settings.gigachat_scope}")


def check_tls(settings: Settings) -> None:
    print("3. Сертификат и TLS до GigaChat")
    if not settings.gigachat_verify_ssl:
        fail("GIGACHAT_VERIFY_SSL=false — проверка TLS выключена, так нельзя в проде")
    bundle = settings.gigachat_ca_bundle
    if bundle:
        path = Path(bundle)
        if not path.is_file():
            warn(f"файл сертификата не найден: {path.resolve()} — хватит встроенного")
        elif "BEGIN CERTIFICATE" not in path.read_text(errors="ignore"):
            fail(f"{bundle} не PEM — нужен .crt/.pem в текстовом виде")
            return
        else:
            count = path.read_text(errors="ignore").count("BEGIN CERTIFICATE")
            ok(f"GIGACHAT_CA_BUNDLE={bundle}, сертификатов в файле: {count}")
    else:
        ok("GIGACHAT_CA_BUNDLE пуст — используется встроенный сертификат российского УЦ")

    # Тот же контекст, что и у приложения: certifi + встроенный сертификат + бандл.
    ctx = make_ssl_context(settings)
    for url in (settings.gigachat_auth_url, settings.gigachat_base_url):
        parts = urlsplit(url)
        host, port = parts.hostname or "", parts.port or 443
        try:
            with socket.create_connection((host, port), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as tls:
                    issuer = dict(x[0] for x in tls.getpeercert()["issuer"])
            ok(f"{host}:{port} — TLS ок, выдан: {issuer.get('commonName')}")
        except ssl.SSLCertVerificationError as e:
            fail(f"{host}:{port} — сертификат не проверен: {e.verify_message}")
        except OSError as e:
            fail(f"{host}:{port} — нет соединения: {e}")


def main() -> None:
    settings = check_settings()
    if settings is not None:
        check_key(settings)
        check_tls(settings)
    print()
    if problems:
        print(f"Проблем: {len(problems)}")
        sys.exit(1)
    print("Всё в порядке")


if __name__ == "__main__":
    main()
