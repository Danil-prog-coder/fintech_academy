"""Готовит back-end/.env: копирует .env.example и генерирует секреты.

    python scripts/setup_env.py              создать .env (если его ещё нет)
    python scripts/setup_env.py --fetch-ca   дополнительно скачать сертификат российского УЦ
                                             для GigaChat в certs/ и прописать путь в .env

После этого остаётся вписать GIGACHAT_CREDENTIALS (и, по желанию, YANDEX_*).
"""

import re
import secrets
import sys
import urllib.request
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
CA_URL = "https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt"
CA_SUB_URL = "https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt"
CA_PATH = "certs/russian_trusted_ca.pem"


def set_var(text: str, name: str, value: str) -> str:
    pattern = re.compile(rf"^{name}=.*$", re.MULTILINE)
    line = f"{name}={value}"
    return pattern.sub(lambda _: line, text, count=1) if pattern.search(text) else text + f"\n{line}\n"


def get_var(text: str, name: str) -> str:
    m = re.search(rf"^{name}=(.*)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def fetch_ca() -> None:
    target = ROOT / CA_PATH
    target.parent.mkdir(exist_ok=True)
    parts = []
    for url in (CA_URL, CA_SUB_URL):
        with urllib.request.urlopen(url, timeout=30) as response:
            parts.append(response.read().decode().strip())
    target.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"Сертификат сохранён: {target}")


def main() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        text = env_path.read_text(encoding="utf-8")
        print(".env уже есть, существующие секреты не меняю.")
    else:
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
    if not get_var(text, "SECRET_KEY") or get_var(text, "SECRET_KEY") == "change-me":
        text = set_var(text, "SECRET_KEY", secrets.token_urlsafe(48))
    if not get_var(text, "ENCRYPTION_KEY"):
        text = set_var(text, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    if not get_var(text, "GITHUB_WEBHOOK_SECRET"):
        text = set_var(text, "GITHUB_WEBHOOK_SECRET", secrets.token_urlsafe(32))
    if "--fetch-ca" in sys.argv:
        fetch_ca()
        # В контейнере каталог certs/ смонтирован в /srv/certs.
        text = set_var(text, "GIGACHAT_CA_BUNDLE", f"/srv/{CA_PATH}")
    env_path.write_text(text, encoding="utf-8")
    print(f"Готово: {env_path}")
    if not get_var(text, "GIGACHAT_CREDENTIALS"):
        print("Осталось вписать GIGACHAT_CREDENTIALS в .env.")


if __name__ == "__main__":
    main()
