"""Jira Cloud REST v3 for support tickets (ported from the Innopolis bot, trimmed to what the platform uses).

* Auth: Basic `email:api_token`; descriptions and comments in Atlassian Document Format.
* Errors become `JiraError` without response bodies or headers, so the token never reaches logs.
* Retries: safe reads (GET, JQL search) are retried on 429 / 5xx / network errors; a POST that may have reached
  Jira raises `JiraAmbiguous` — the caller reconciles (issue creation looks the issue up by its idempotency label)
  instead of posting blindly again.
* Redirects are never followed: the Authorization header must not travel to another host.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx

SUMMARY_MAX_LEN = 255
FINAL_STATUSES = frozenset({"Готово", "Решено", "Отменено", "Done", "Closed", "Resolved", "Canceled", "Cancelled"})
# Comments the platform writes itself: the webhook must not echo them back to the user
PLATFORM_PREFIXES = ("[Пользователь]", "[Поддержка]", "[Платформа]")
INTERNAL_PREFIX = "//"
ISSUE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")
PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")
IDEMPOTENCY_LABEL_PREFIX = "idem-"

# Our ticket status → a Jira status name tried on transition (the first name that exists in the workflow wins)
STATUS_TO_JIRA = {
    "waiting": ("To Do", "Открыто", "Open"),
    "in_progress": ("In Progress", "В работе"),
    "waiting_customer": ("Waiting for customer", "Ожидает клиента", "In Progress", "В работе"),
    "resolved": ("Done", "Решено", "Готово", "Resolved"),
    "closed": ("Done", "Готово", "Closed", "Решено"),
}


class JiraError(Exception):
    """Jira is unreachable or rejected the request. The message never contains secrets."""


class JiraAmbiguous(JiraError):
    """A POST may or may not have been applied (network / 5xx after sending)."""


@dataclass(frozen=True)
class JiraConfig:
    base_url: str
    email: str
    api_token: str
    project_key: str
    issue_type: str = "Task"


def idempotency_label(key: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9_-]", "-", key.strip()).strip("-")[:64] or "default"
    return IDEMPOTENCY_LABEL_PREFIX + raw


def adf(text: str) -> dict[str, Any]:
    paragraphs = [{"type": "paragraph", "content": [{"type": "text", "text": line}] if line else []}
                  for line in text.split("\n")]
    return {"type": "doc", "version": 1, "content": paragraphs}


def adf_to_text(body: Any) -> str:
    if isinstance(body, str):
        return body.strip()
    lines: list[str] = []
    current: list[str] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        kind = node.get("type")
        if kind == "text":
            current.append(str(node.get("text") or ""))
        elif kind == "hardBreak":
            current.append("\n")
        for child in node.get("content") or ():
            walk(child)
        if kind in ("paragraph", "heading", "listItem", "codeBlock", "blockquote"):
            lines.append("".join(current))
            current.clear()

    walk(body)
    if current:
        lines.append("".join(current))
    return "\n".join(line for line in lines if line.strip()).strip()


def _jql_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class JiraClient:
    def __init__(self, config: JiraConfig, http: httpx.AsyncClient, timeout_s: float = 20.0) -> None:
        if not config.base_url.startswith("https://") and not config.base_url.startswith("http://localhost"):
            raise JiraError("Jira base URL must be https")
        if not PROJECT_KEY_RE.match(config.project_key):
            raise JiraError("bad Jira project key")
        self._cfg = config
        self._http = http
        self._timeout = timeout_s
        token = base64.b64encode(f"{config.email}:{config.api_token}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}

    async def _request(self, method: str, path: str, *, safe: bool = False, **kw) -> httpx.Response:
        url = self._cfg.base_url.rstrip("/") + path
        attempts = 3 if safe else 1
        for attempt in range(attempts + 2):
            try:
                r = await self._http.request(method, url, headers=self._headers, timeout=self._timeout,
                                             follow_redirects=False, **kw)
            except httpx.HTTPError as e:
                if safe and attempt < attempts:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise (JiraError if safe else JiraAmbiguous)(f"Jira {method} {path.split('?')[0]}: {type(e).__name__}") from None
            if r.status_code == 429 and attempt < attempts + 1:
                await asyncio.sleep(min(float(r.headers.get("Retry-After") or 1), 5))
                continue
            if r.status_code >= 500:
                if safe and attempt < attempts:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise (JiraError if safe else JiraAmbiguous)(f"Jira {method} {path.split('?')[0]}: HTTP {r.status_code}")
            if 300 <= r.status_code < 400:
                raise JiraError("Jira answered with a redirect: check the base URL")
            if r.status_code >= 400:
                raise JiraError(f"Jira {method} {path.split('?')[0]}: HTTP {r.status_code}")
            return r
        raise JiraError("Jira: too many retries")

    async def check(self) -> dict:
        r = await self._request("GET", f"/rest/api/3/project/{self._cfg.project_key}", safe=True)
        data = r.json()
        return {"key": data.get("key"), "name": data.get("name")}

    async def find_by_label(self, label: str) -> str | None:
        jql = f"project = {self._cfg.project_key} AND labels = {_jql_quote(label)}"
        r = await self._request("POST", "/rest/api/3/search/jql", safe=True,
                                json={"jql": jql, "fields": ["key"], "maxResults": 2})
        issues = r.json().get("issues") or []
        keys = [i.get("key") for i in issues if isinstance(i, dict) and ISSUE_KEY_RE.match(str(i.get("key") or ""))]
        return keys[0] if keys else None

    async def create_issue(self, summary: str, description: str, labels: list[str], priority: str,
                           idempotency_key: str) -> str:
        """Create once: the issue carries a label derived from our ticket id; a retry finds it instead of duplicating."""
        label = idempotency_label(idempotency_key)
        existing = await self.find_by_label(label)
        if existing:
            return existing
        payload = {"fields": {
            "project": {"key": self._cfg.project_key}, "issuetype": {"name": self._cfg.issue_type},
            "summary": summary[:SUMMARY_MAX_LEN], "description": adf(description),
            "labels": list(dict.fromkeys([*labels, label])), "priority": {"name": priority},
        }}
        try:
            r = await self._request("POST", "/rest/api/3/issue", json=payload)
        except JiraAmbiguous:
            found = await self.find_by_label(label)
            if found:
                return found
            raise
        key = r.json().get("key")
        if not isinstance(key, str) or not ISSUE_KEY_RE.match(key):
            raise JiraAmbiguous("Jira returned an unexpected issue shape")
        return key

    async def add_comment(self, key: str, text: str) -> str | None:
        if not ISSUE_KEY_RE.match(key):
            raise JiraError("bad issue key")
        r = await self._request("POST", f"/rest/api/3/issue/{key}/comment", json={"body": adf(text[:32000])})
        cid = r.json().get("id")
        return str(cid) if cid is not None else None

    async def transition(self, key: str, status: str) -> bool:
        """Move the issue to our status; False — the workflow has no matching transition (not an error)."""
        if not ISSUE_KEY_RE.match(key):
            raise JiraError("bad issue key")
        r = await self._request("GET", f"/rest/api/3/issue/{key}/transitions", safe=True)
        transitions = r.json().get("transitions") or []
        wanted = [n.casefold() for n in STATUS_TO_JIRA.get(status, (status,))]
        for name in wanted:
            for t in transitions:
                to_name = str((t.get("to") or {}).get("name") or "").casefold()
                if name in (str(t.get("name") or "").casefold(), to_name):
                    await self._request("POST", f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": t["id"]}})
                    return True
        return False


@dataclass(frozen=True)
class JiraEvent:
    kind: Literal["assigned", "status_changed", "closed", "comment"]
    issue_key: str
    status: str | None = None
    comment_text: str | None = None
    comment_author: str | None = None
    comment_id: str | None = None


def verify_signature(body: bytes, signature: str | None, secret: str | None) -> bool:
    if not signature or not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_webhook(payload: dict[str, Any]) -> JiraEvent | None:
    event = payload.get("webhookEvent")
    key = (payload.get("issue") or {}).get("key")
    if not isinstance(key, str) or not ISSUE_KEY_RE.match(key):
        return None
    if event == "comment_created":
        comment = payload.get("comment") or {}
        if not isinstance(comment, dict) or comment.get("jsdPublic") is False:
            return None  # an internal Jira Service Management comment is not for the user
        text = adf_to_text(comment.get("body"))
        if not text or text.startswith((*PLATFORM_PREFIXES, INTERNAL_PREFIX)):
            return None
        author = (comment.get("author") or {}).get("displayName") if isinstance(comment.get("author"), dict) else None
        cid = comment.get("id")
        return JiraEvent("comment", key, comment_text=text, comment_author=author,
                         comment_id=str(cid) if cid is not None else None)
    if event != "jira:issue_updated":
        return None
    for item in (payload.get("changelog") or {}).get("items") or ():
        if not isinstance(item, dict):
            continue
        if item.get("field") == "assignee" and item.get("to"):
            return JiraEvent("assigned", key)
        if item.get("field") == "status" and isinstance(item.get("toString"), str):
            status = item["toString"]
            return JiraEvent("closed" if status in FINAL_STATUSES else "status_changed", key, status=status)
    return None
