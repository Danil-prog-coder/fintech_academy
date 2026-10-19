import hashlib
import hmac
import re
from dataclasses import dataclass

import httpx
from fastapi import Request

from app.core.errors import AppError

_URL_RE = re.compile(r"^https?://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def parse_repo_url(url: str) -> tuple[str, str]:
    m = _URL_RE.match(url.strip())
    if not m:
        raise AppError(
            "invalid_repo_url", "Ссылка должна иметь вид https://github.com/владелец/репозиторий.", 422
        )
    return m.group(1), m.group(2)


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Проверка X-Hub-Signature-256 сравнением постоянного времени."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@dataclass
class RepoInfo:
    default_branch: str
    private: bool


class GitHubClient:
    """Клиент GitHub. Один httpx.AsyncClient на приложение (создаётся в lifespan)."""

    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    async def check_access(self, owner: str, name: str, token: str | None) -> RepoInfo:
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            r = await self._http.get(f"https://api.github.com/repos/{owner}/{name}", headers=headers)
        except httpx.HTTPError:
            raise AppError("github_unavailable", "GitHub недоступен, попробуйте позже.", 502, True)
        if r.status_code == 200:
            data = r.json()
            return RepoInfo(default_branch=data["default_branch"], private=data["private"])
        if r.status_code == 401:
            raise AppError("invalid_github_token", "Токен GitHub недействителен.", 400)
        if r.status_code in (403, 404):
            raise AppError(
                "repo_no_access",
                "Репозиторий не найден или у токена нет к нему доступа.",
                400,
            )
        raise AppError("github_unavailable", "GitHub вернул ошибку, попробуйте позже.", 502, True)


def get_github(request: Request) -> GitHubClient:
    return request.app.state.github
