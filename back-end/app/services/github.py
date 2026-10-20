import base64
import hashlib
import hmac
import re
from dataclasses import dataclass

import httpx
from fastapi import Request

from app.core.errors import AppError

_URL_RE = re.compile(r"^https?://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
API = "https://api.github.com"


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


class GitHubAuthError(Exception):
    """Токен отозван или потерян доступ к репозиторию → статус reauth_required."""


class GitHubUnavailableError(Exception):
    """Сеть, 5xx или лимит запросов GitHub: имеет смысл повторить позже."""


@dataclass
class RepoInfo:
    default_branch: str
    private: bool


@dataclass
class HeadCommit:
    sha: str
    author: str | None
    date: str | None


@dataclass
class TreeEntry:
    path: str
    sha: str
    size: int


@dataclass
class ChangedFile:
    path: str
    status: str  # added | modified | removed | renamed | ...
    previous_path: str | None = None


@dataclass
class Issue:
    number: int
    title: str
    body: str
    url: str
    state: str
    is_pr: bool


class GitHubClient:
    """Клиент GitHub. Один httpx.AsyncClient на процесс (создаётся при старте)."""

    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    # --- общее ------------------------------------------------------------------------

    @staticmethod
    def _headers(token: str | None) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _request(
        self, method: str, path: str, token: str | None, **kwargs
    ) -> httpx.Response:
        try:
            return await self._http.request(
                method, f"{API}{path}", headers=self._headers(token), **kwargs
            )
        except httpx.HTTPError:
            raise GitHubUnavailableError from None

    @staticmethod
    def _check(r: httpx.Response, *, has_token: bool) -> None:
        """Переводит коды GitHub в наши исключения; 2xx проходит."""
        if r.status_code < 400:
            return
        if r.status_code == 401:
            raise GitHubAuthError
        if r.status_code == 403:
            if r.headers.get("x-ratelimit-remaining") == "0" or "rate limit" in r.text.lower():
                raise GitHubUnavailableError
            raise GitHubAuthError
        if r.status_code == 404:
            raise GitHubAuthError  # приватный репозиторий без доступа выглядит как 404
        raise GitHubUnavailableError

    # --- подключение ------------------------------------------------------------------

    async def check_access(self, owner: str, name: str, token: str | None) -> RepoInfo:
        try:
            r = await self._request("GET", f"/repos/{owner}/{name}", token)
        except GitHubUnavailableError:
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

    async def create_webhook(
        self, owner: str, name: str, token: str, url: str, secret: str
    ) -> int | None:
        """id вебхука или None, если у токена нет прав (тогда пользователь настраивает вручную)."""
        body = {
            "name": "web",
            "active": True,
            "events": ["push"],
            "config": {"url": url, "content_type": "json", "secret": secret, "insecure_ssl": "0"},
        }
        try:
            r = await self._request("POST", f"/repos/{owner}/{name}/hooks", token, json=body)
        except GitHubUnavailableError:
            return None
        if r.status_code == 201:
            return r.json().get("id")
        return None

    async def delete_webhook(self, owner: str, name: str, token: str, hook_id: int) -> None:
        try:
            await self._request("DELETE", f"/repos/{owner}/{name}/hooks/{hook_id}", token)
        except GitHubUnavailableError:
            pass  # вебхук останется на стороне GitHub; приложение игнорирует его события

    # --- чтение для индексации --------------------------------------------------------

    async def head_commit(self, owner: str, name: str, branch: str, token: str | None) -> HeadCommit:
        r = await self._request("GET", f"/repos/{owner}/{name}/commits/{branch}", token)
        self._check(r, has_token=bool(token))
        data = r.json()
        commit = data.get("commit") or {}
        author = commit.get("author") or {}
        return HeadCommit(sha=data["sha"], author=author.get("name"), date=author.get("date"))

    async def list_tree(
        self, owner: str, name: str, sha: str, token: str | None
    ) -> list[TreeEntry]:
        r = await self._request("GET", f"/repos/{owner}/{name}/git/trees/{sha}", token, params={"recursive": "1"})
        self._check(r, has_token=bool(token))
        return [
            TreeEntry(path=e["path"], sha=e["sha"], size=e.get("size", 0))
            for e in r.json().get("tree", [])
            if e.get("type") == "blob"
        ]

    async def get_blob(self, owner: str, name: str, sha: str, token: str | None) -> bytes:
        r = await self._request("GET", f"/repos/{owner}/{name}/git/blobs/{sha}", token)
        self._check(r, has_token=bool(token))
        data = r.json()
        if data.get("encoding") == "base64":
            return base64.b64decode(data.get("content", ""))
        return (data.get("content") or "").encode()

    async def compare(
        self, owner: str, name: str, base: str, head: str, token: str | None
    ) -> list[ChangedFile] | None:
        """Изменённые файлы между коммитами или None, если сравнить нельзя (нужна полная сборка)."""
        r = await self._request("GET", f"/repos/{owner}/{name}/compare/{base}...{head}", token, params={"per_page": 100})
        if r.status_code in (404, 422):
            return None
        self._check(r, has_token=bool(token))
        data = r.json()
        files = data.get("files") or []
        if len(files) >= 300 or data.get("total_commits", 0) > 250:
            return None  # GitHub обрезает такие ответы
        return [
            ChangedFile(f["filename"], f.get("status", "modified"), f.get("previous_filename"))
            for f in files
        ]

    async def list_issues(
        self, owner: str, name: str, token: str | None, pages: int
    ) -> list[Issue]:
        out: list[Issue] = []
        for page in range(1, pages + 1):
            r = await self._request(
                "GET",
                f"/repos/{owner}/{name}/issues",
                token,
                params={"state": "all", "per_page": 100, "page": page},
            )
            if r.status_code in (404, 410):  # issues отключены в репозитории
                break
            self._check(r, has_token=bool(token))
            batch = r.json()
            for item in batch:
                out.append(
                    Issue(
                        number=item["number"],
                        title=item.get("title") or "",
                        body=item.get("body") or "",
                        url=item.get("html_url") or "",
                        state=item.get("state") or "",
                        is_pr="pull_request" in item,
                    )
                )
            if len(batch) < 100:
                break
        return out


def get_github(request: Request) -> GitHubClient:
    return request.app.state.github
