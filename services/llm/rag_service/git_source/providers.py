"""GitProvider (FR-GIT-01/02): GitHub and GitLab (incl. self-hosted by base URL) through their REST APIs.

No git binary and no clone: the bot reads the tree at a commit, downloads matching files, and asks the provider
for the diff between the last indexed commit and the new head (FR-GIT-03). Links to sources are pinned to the
commit SHA with a heading anchor or a line range (FR-GIT-02). Tokens are sent only in headers, never logged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

import httpx  # BSD

from ..config import get_settings


@dataclass
class RepoFile:
    path: str
    size: int
    blob_sha: str


@dataclass
class Change:
    status: str  # added | modified | removed | renamed
    path: str
    previous_path: str | None = None


class GitError(RuntimeError):
    pass


class GitProvider(Protocol):
    name: str

    def head(self) -> str: ...

    def list_files(self, sha: str) -> list[RepoFile]: ...

    def fetch(self, sha: str, path: str) -> bytes: ...

    def compare(self, base: str, head: str) -> list[Change]: ...

    def blob_url(self, sha: str, path: str, anchor: str | None = None, lines: tuple[int, int] | None = None) -> str: ...

    def check_access(self) -> dict: ...


def heading_anchor(text: str, provider: str = "github") -> str:
    """GitHub/GitLab heading slug: lower-case, punctuation removed (letters incl. Cyrillic kept), spaces → «-»."""
    s = re.sub(r"[^\w\- ]", "", (text or "").strip().lower())
    s = s.replace(" ", "-")
    if provider == "gitlab":
        s = re.sub(r"-{2,}", "-", s)
    return s


class _Http:
    def __init__(self, token: str | None, auth_header: str, auth_prefix: str = "") -> None:
        h = {"User-Agent": "rag-service"}
        if token:
            h[auth_header] = f"{auth_prefix}{token}"
        self._c = httpx.Client(headers=h, timeout=get_settings().git_timeout_s, follow_redirects=True)

    def get(self, url: str, **kw) -> httpx.Response:
        try:
            r = self._c.get(url, **kw)
        except httpx.HTTPError as e:
            raise GitError(f"network error: {type(e).__name__}") from None
        if r.status_code >= 400:
            # never include headers (token) in the error
            raise GitError(f"HTTP {r.status_code} for {url.split('?')[0]}: {r.text[:200]}")
        return r


class GitHubProvider:
    name = "github"

    def __init__(self, repo: str, branch: str, token: str | None = None, base_url: str = "https://github.com") -> None:
        self.repo = repo.strip("/")
        self.branch = branch
        self.base_url = base_url.rstrip("/")
        self.api = "https://api.github.com" if "github.com" in self.base_url else f"{self.base_url}/api/v3"
        self.http = _Http(token, "Authorization", "Bearer ")

    def head(self) -> str:
        return self.http.get(f"{self.api}/repos/{self.repo}/commits/{quote(self.branch, safe='')}",
                             headers={"Accept": "application/vnd.github+json"}).json()["sha"]

    def list_files(self, sha: str) -> list[RepoFile]:
        d = self.http.get(f"{self.api}/repos/{self.repo}/git/trees/{sha}", params={"recursive": "1"}).json()
        return [RepoFile(t["path"], int(t.get("size") or 0), t["sha"]) for t in d.get("tree", []) if t.get("type") == "blob"]

    def fetch(self, sha: str, path: str) -> bytes:
        return self.http.get(f"{self.api}/repos/{self.repo}/contents/{quote(path)}", params={"ref": sha},
                             headers={"Accept": "application/vnd.github.raw"}).content

    def compare(self, base: str, head: str) -> list[Change]:
        d = self.http.get(f"{self.api}/repos/{self.repo}/compare/{base}...{head}").json()
        files = d.get("files") or []
        if len(files) >= 300:
            raise GitError("diff too large for the compare API")  # caller falls back to a full import
        out = []
        for f in files:
            st = {"added": "added", "removed": "removed", "renamed": "renamed"}.get(f.get("status"), "modified")
            out.append(Change(st, f["filename"], f.get("previous_filename")))
        return out

    def blob_url(self, sha: str, path: str, anchor: str | None = None, lines: tuple[int, int] | None = None) -> str:
        u = f"{self.base_url}/{self.repo}/blob/{sha}/{quote(path)}"
        if lines:
            return u + f"#L{lines[0]}-L{lines[1]}"
        return u + (f"#{anchor}" if anchor else "")

    def check_access(self) -> dict:
        d = self.http.get(f"{self.api}/repos/{self.repo}").json()
        return {"ok": True, "private": d.get("private"), "default_branch": d.get("default_branch"),
                "can_push": (d.get("permissions") or {}).get("push")}


class GitLabProvider:
    name = "gitlab"

    def __init__(self, repo: str, branch: str, token: str | None = None, base_url: str = "https://gitlab.com") -> None:
        self.repo = repo.strip("/")
        self.branch = branch
        self.base_url = base_url.rstrip("/")
        self.pid = quote(self.repo, safe="")
        self.api = f"{self.base_url}/api/v4/projects/{self.pid}"
        self.http = _Http(token, "PRIVATE-TOKEN")

    def head(self) -> str:
        return self.http.get(f"{self.api}/repository/branches/{quote(self.branch, safe='')}").json()["commit"]["id"]

    def list_files(self, sha: str) -> list[RepoFile]:
        out, page = [], "1"
        while page:
            r = self.http.get(f"{self.api}/repository/tree", params={"ref": sha, "recursive": "true", "per_page": 100, "page": page})
            out += [RepoFile(t["path"], 0, t["id"]) for t in r.json() if t.get("type") == "blob"]
            page = r.headers.get("X-Next-Page") or ""
        return out

    def fetch(self, sha: str, path: str) -> bytes:
        return self.http.get(f"{self.api}/repository/files/{quote(path, safe='')}/raw", params={"ref": sha}).content

    def compare(self, base: str, head: str) -> list[Change]:
        d = self.http.get(f"{self.api}/repository/compare", params={"from": base, "to": head}).json()
        out = []
        for f in d.get("diffs") or []:
            if f.get("deleted_file"):
                out.append(Change("removed", f["old_path"]))
            elif f.get("new_file"):
                out.append(Change("added", f["new_path"]))
            elif f.get("renamed_file"):
                out.append(Change("renamed", f["new_path"], f["old_path"]))
            else:
                out.append(Change("modified", f["new_path"]))
        return out

    def blob_url(self, sha: str, path: str, anchor: str | None = None, lines: tuple[int, int] | None = None) -> str:
        u = f"{self.base_url}/{self.repo}/-/blob/{sha}/{quote(path)}"
        if lines:
            return u + f"#L{lines[0]}-{lines[1]}"
        return u + (f"#{anchor}" if anchor else "")

    def check_access(self) -> dict:
        d = self.http.get(self.api).json()
        return {"ok": True, "private": d.get("visibility") != "public", "default_branch": d.get("default_branch")}


def make_provider(src: dict, token: str | None) -> GitProvider:
    if src["provider"] == "gitlab":
        return GitLabProvider(src["repo"], src["branch"], token, src.get("base_url") or "https://gitlab.com")
    if src["provider"] == "github":
        return GitHubProvider(src["repo"], src["branch"], token, src.get("base_url") or "https://github.com")
    raise GitError(f"unknown provider {src['provider']!r}")
