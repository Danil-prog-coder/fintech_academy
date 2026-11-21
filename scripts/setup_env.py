#!/usr/bin/env python3
"""Create services/*/.env from .env.example with fresh secrets, consistent across the services.

    python scripts/setup_env.py                      # local run (http://localhost:3000 / :3001)
    python scripts/setup_env.py --domain platform.example.com --mail-domain mail.example.com   # a VPS behind HTTPS

Secrets shared by two services are generated once and written to both:
  llm ADMIN_API_TOKEN  = admin RAG_API_TOKEN       (admin → llm)
  admin BOOTSTRAP_INTEGRATIONS key = mail PLATFORM_API_KEY   (mail → admin /v1)
Existing .env files are left untouched (use --force to overwrite). Model keys (OPENROUTER_API_KEY) are not
generated: put them into services/llm/.env yourself.
"""

from __future__ import annotations

import argparse
import base64
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def token(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


def fernet_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def fill(example: Path, values: dict[str, str]) -> str:
    out = []
    for line in example.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(#\s*)?([A-Z0-9_]+)=", line)
        if m and m.group(2) in values:
            line = f"{m.group(2)}={values[m.group(2)]}"
        out.append(line)
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", help="public domain of the admin site and API (HTTPS)")
    ap.add_argument("--mail-domain", help="public domain of the mail demo (HTTPS)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    admin_url = f"https://{args.domain}" if args.domain else "http://localhost:3001"
    rag_token, integration_key = token(), "ik_mail-demo_" + token()
    plan = {
        ROOT / "services/llm": {
            "ADMIN_API_TOKEN": rag_token, "DOC_LINK_SECRET": token(), "PUBLIC_BASE_URL": f"{admin_url}/v1/public/rag",
        },
        ROOT / "services/admin/backend": {
            "SECRET_KEY": token(48), "RAG_API_TOKEN": rag_token, "PANEL_PUBLIC_URL": admin_url, "API_PUBLIC_URL": admin_url,
            "COOKIE_SECURE": "true" if args.domain else "false",
            "BOOTSTRAP_INTEGRATIONS": f"mail-demo:Почта (демо):{integration_key}",
        },
        ROOT / "services/mail/backend": {
            "SECRET_KEY": token(48), "ENCRYPTION_KEY": fernet_key(), "PLATFORM_API_KEY": integration_key,
        },
    }
    for folder, values in plan.items():
        env = folder / ".env"
        if env.exists() and not args.force:
            print(f"skip {env.relative_to(ROOT)} (exists; --force to overwrite)")
            continue
        env.write_text(fill(folder / ".env.example", values), encoding="utf-8")
        env.chmod(0o600)
        print(f"wrote {env.relative_to(ROOT)}")
    print("\nNext: put OPENROUTER_API_KEY into services/llm/.env, then  docker compose up -d --build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
