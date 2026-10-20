"""Заглушки внешних сервисов для e2e: GitHub, GigaChat (чат и эмбеддинги), YandexGPT.

Это не моки отдельных функций, а HTTP-ответы: приложение ходит в них своими настоящими
клиентами. Эмбеддинги — детерминированный «мешок слов» (близость текстов осмысленна), а
«нейросеть» отвечает по тем фрагментам, что реально попали в её промпт.
"""

import base64
import hashlib
import json
import math
import re
import zlib

import httpx

DIM = 1024
SCOPE_MARK = "фильтр запросов"
OFFTOPIC_WORDS = ("погод", "борщ")

DEFAULT_FILES: dict[str, bytes | str] = {
    "README.md": (
        "# Проект Альфа\n\nДеплой выполняется командой `make deploy` из ветки main.\n"
        "Релизы публикуются по тегам вида vX.Y.Z.\n"
    ),
    "docs/release.md": (
        "# Процесс релиза\n\n1. Обновите CHANGELOG.md.\n2. Создайте тег релиза.\n"
        "3. Дождитесь зелёного CI и подтвердите выкладку.\n"
    ),
    "src/billing.py": (
        "def calculate_invoice(items):\n"
        '    """Расчёт счёта: сумма позиций плюс НДС 20 процентов."""\n'
        "    return sum(items) * 1.2\n"
    ),
    "config/settings.yml": "database:\n  host: db.internal\n  port: 5432\n",
    ".env": "SECRET_KEY=super-secret-value-do-not-index\n",
    ".env.example": "SECRET_KEY=change-me\n",
    "keys/server.pem": "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n",
    "src/leaky.py": 'API_KEY = "sk_" "live_abcdefghijklmnopqrstuvwxyz123456"\n',
    "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00binary",
    "package-lock.json": '{"lockfileVersion": 3}',
    "node_modules/lib/index.js": "module.exports = 1;\n",
}

ISSUES = [
    {
        "number": 7,
        "title": "Падает выгрузка отчёта",
        "body": "Выгрузка отчёта по клиентам падает с таймаутом на больших объёмах.",
        "html_url": "https://github.com/acme/project/issues/7",
        "state": "open",
    },
    {
        "number": 8,
        "title": "Добавить экспорт в CSV",
        "body": "Нужен экспорт таблицы платежей.",
        "html_url": "https://github.com/acme/project/pull/8",
        "state": "closed",
        "pull_request": {"url": "x"},
    },
]


def _sha(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _bytes(content: bytes | str) -> bytes:
    return content.encode() if isinstance(content, str) else content


class FakeRepoState:
    def __init__(self):
        self.history: list[tuple[str, dict[str, bytes]]] = []
        self.issues = [dict(i) for i in ISSUES]
        self.commit({p: c for p, c in DEFAULT_FILES.items()}, "initial")

    def commit(self, changes: dict[str, bytes | str | None], message: str = "change") -> str:
        snapshot = dict(self.history[-1][1]) if self.history else {}
        for path, content in changes.items():
            if content is None:
                snapshot.pop(path, None)
            else:
                snapshot[path] = _bytes(content)
        sha = _sha(f"{message}{len(self.history)}{sorted(snapshot)}".encode())
        self.history.append((sha, snapshot))
        return sha

    @property
    def head(self) -> str:
        return self.history[-1][0]

    def snapshot(self, sha: str) -> dict[str, bytes] | None:
        return next((snap for s, snap in self.history if s == sha), None)

    def blob(self, sha: str) -> bytes | None:
        for _, snap in self.history:
            for content in snap.values():
                if _sha(content) == sha:
                    return content
        return None


class FakeGitHub:
    def __init__(self):
        self.repos: dict[str, FakeRepoState] = {}
        self.calls: list[httpx.Request] = []
        self.failure: str | None = None  # "5xx" | "network"
        self.head_failures = 0  # следующие N запросов HEAD-коммита отвечают 503
        self.revoked_tokens: set[str] = set()
        self.created_hooks: list[dict] = []
        self.deleted_hooks: list[str] = []
        self.hooks_allowed = True

    def repo(self, owner: str, name: str) -> FakeRepoState:
        return self.repos.setdefault(f"{owner}/{name}".lower(), FakeRepoState())

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.failure == "network":
            raise httpx.ConnectError("boom", request=request)
        if self.failure == "5xx":
            return httpx.Response(502)
        auth = request.headers.get("Authorization")
        token = auth.removeprefix("Bearer ") if auth else None
        match = re.match(r"^/repos/([^/]+)/([^/]+)(/.*)?$", request.url.path)
        assert match, request.url
        owner, name, rest = match.group(1), match.group(2), match.group(3) or ""
        if token == "bad" or token in self.revoked_tokens:
            return httpx.Response(401)
        if owner == "acme" and name.startswith("secret") and token != "ghp_secret":
            return httpx.Response(404)  # приватный репозиторий без доступа
        repo = self.repo(owner, name)

        if request.method == "POST" and rest == "/hooks":
            if token is None or not self.hooks_allowed:
                return httpx.Response(404)
            self.created_hooks.append(json.loads(request.content))
            return httpx.Response(201, json={"id": 77})
        if request.method == "DELETE" and rest.startswith("/hooks/"):
            self.deleted_hooks.append(rest.rsplit("/", 1)[1])
            return httpx.Response(204)
        if rest == "":
            return httpx.Response(200, json={"default_branch": "main", "private": token is not None})
        if rest.startswith("/commits/"):
            if self.head_failures > 0:
                self.head_failures -= 1
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={
                    "sha": repo.head,
                    "commit": {"author": {"name": "Dev", "date": "2026-10-20T10:00:00Z"}},
                },
            )
        if rest.startswith("/git/trees/"):
            snap = repo.snapshot(rest.rsplit("/", 1)[1])
            if snap is None:
                return httpx.Response(404)
            tree = [
                {"path": p, "type": "blob", "sha": _sha(c), "size": len(c)}
                for p, c in sorted(snap.items())
            ]
            return httpx.Response(200, json={"tree": tree, "truncated": False})
        if rest.startswith("/git/blobs/"):
            data = repo.blob(rest.rsplit("/", 1)[1])
            if data is None:
                return httpx.Response(404)
            return httpx.Response(
                200, json={"content": base64.b64encode(data).decode(), "encoding": "base64"}
            )
        if rest.startswith("/compare/"):
            base, head = rest.removeprefix("/compare/").split("...")
            a, b = repo.snapshot(base), repo.snapshot(head)
            if a is None or b is None:
                return httpx.Response(404)
            files = [
                {"filename": p, "status": "added" if p not in a else "modified"}
                for p in b
                if a.get(p) != b[p]
            ] + [{"filename": p, "status": "removed"} for p in a if p not in b]
            return httpx.Response(200, json={"files": files, "total_commits": 1})
        if rest == "/issues":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=repo.issues if page == 1 else [])
        return httpx.Response(404)


# --- нейросеть --------------------------------------------------------------------------


def embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for word in re.findall(r"\w+", text.lower()):
        if len(word) >= 3:
            vec[zlib.crc32(word[:5].encode()) % DIM] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"\w+", text.lower()) if len(w) >= 4}


_FRAGMENT = re.compile(r'<фрагмент n="(\d+)" path="([^"]*)" lines="([^"]*)">\n(.*?)\n</фрагмент>', re.DOTALL)
_QUESTION = re.compile(r"<вопрос>\n(.*?)\n</вопрос>", re.DOTALL)


def chat_reply(messages: list[dict]) -> str:
    """Что ответила бы «нейросеть» на запрос проверки оффтопа или на вопрос по контексту."""
    system, user = messages[0]["content"], messages[-1]["content"]
    question = (_QUESTION.search(user) or [None, user])[1]
    if SCOPE_MARK in system:
        offtopic = any(w in question.lower() for w in OFFTOPIC_WORDS)
        return json.dumps({"in_scope": not offtopic})

    wanted = _stems(question)
    scored = []
    for n, _path, _lines, text in _FRAGMENT.findall(user):
        overlap = len(wanted & _stems(text))
        if overlap:
            scored.append((overlap, int(n), text))
    if not scored:
        return json.dumps({"status": "not_found", "answer": "", "sources": []})
    scored.sort(reverse=True)
    best = scored[:2]
    lines = [line for line in best[0][2].splitlines() if line.strip()]
    first_line = max(lines, key=lambda line: len(wanted & _stems(line)))  # самая подходящая строка
    status = "partial" if "частично" in question.lower() else "answered"
    return json.dumps(
        {
            "status": status,
            "answer": f"{first_line.strip()[:160]} [{best[0][1]}]",
            "sources": [n for _, n, _ in best],
        },
        ensure_ascii=False,
    )
