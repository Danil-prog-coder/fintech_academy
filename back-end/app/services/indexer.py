"""Индексация репозитория: файлы и issues/PR → фрагменты → эмбеддинги → версия индекса.

Версия индекса собирается рядом с активной, а переключается одной транзакцией, поэтому
ответы во время обновления строятся по прежней версии (FR-IDX-05). Повторный запуск на
том же коммите ничего не делает (FR-IDX-04). Неизменившиеся фрагменты при обновлении
копируются вместе с векторами и заново не считаются.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.security import decrypt_secret
from app.db.models import Chunk, IndexVersion, Repository
from app.llm.base import EmbeddingProvider
from app.services.github import ChangedFile, GitHubClient, Issue, TreeEntry

log = logging.getLogger(__name__)

BLOB_CONCURRENCY = 8
MAX_CHUNKS_PER_FILE = 200
EMBED_TEXT_CHARS = 2000

SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", "target", "vendor", "__pycache__", ".venv",
    "venv", ".idea", ".vscode", ".next", "coverage", ".mypy_cache", ".pytest_cache",
}  # fmt: skip
SKIP_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Cargo.lock",
    "Pipfile.lock", "composer.lock", "go.sum",
}  # fmt: skip
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg", ".pdf", ".zip", ".gz",
    ".tar", ".tgz", ".rar", ".7z", ".jar", ".war", ".class", ".exe", ".dll", ".so", ".dylib",
    ".bin", ".woff", ".woff2", ".ttf", ".eot", ".otf", ".mp3", ".mp4", ".mov", ".avi", ".wav",
    ".psd", ".sketch", ".pyc", ".o", ".a", ".min.js", ".min.css", ".map", ".db", ".sqlite",
}  # fmt: skip
# Файлы с секретами в индекс не попадают (FR-IDX-06).
SECRET_NAMES = re.compile(
    r"(^|/)(\.env(\..+)?|id_rsa|id_dsa|id_ecdsa|id_ed25519|.*\.(pem|key|p12|pfx|jks|keystore|crt|cer)"
    r"|\.npmrc|\.pypirc|credentials(\.json)?|secrets?\.(json|ya?ml|toml))$",
    re.IGNORECASE,
)
SECRET_EXAMPLES = re.compile(r"\.(example|sample|template|dist)$", re.IGNORECASE)
SECRET_CONTENT = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|AKIA[0-9A-Z]{16}"
    r"|gh[pousr]_[A-Za-z0-9]{30,}"
    r"|xox[abp]-[A-Za-z0-9-]{20,}"
    r"|(?i:api[_-]?key|secret|token|passwd|password)[\"']?\s*[:=]\s*[\"'][A-Za-z0-9/+_\-]{20,}[\"']"
)
DOC_EXT = {".md", ".markdown", ".rst", ".txt", ".adoc"}
CONFIG_EXT = {".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".xml"}


def file_kind(path: str) -> str:
    name = PurePosixPath(path).name
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in DOC_EXT or name.upper().startswith(("README", "CHANGELOG", "LICENSE")):
        return "doc"
    if suffix in CONFIG_EXT or name in {"Dockerfile", "Makefile"} or name.startswith("Dockerfile"):
        return "config"
    return "code"


def skip_reason(path: str, size: int) -> str | None:
    """Почему файл не индексируем, или None."""
    parts = path.split("/")
    name = parts[-1]
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return "dir"
    if name in SKIP_NAMES or any(path.lower().endswith(e) for e in SKIP_EXTENSIONS):
        return "binary"
    if SECRET_NAMES.search(path) and not SECRET_EXAMPLES.search(path):
        return "secret"
    if size > get_settings().max_file_bytes:
        return "large"
    return None


def decode_text(data: bytes) -> str | None:
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def has_secret(text: str) -> bool:
    return bool(SECRET_CONTENT.search(text))


@dataclass
class Piece:
    path: str
    kind: str
    text: str
    start_line: int | None = None
    end_line: int | None = None
    meta: dict = field(default_factory=dict)


def chunk_text(text: str, size: int) -> list[tuple[int, int, str]]:
    """Режет по строкам окнами ~size символов с перекрытием в пару строк."""
    lines = text.splitlines()
    out: list[tuple[int, int, str]] = []
    buf: list[tuple[int, str]] = []
    length = 0

    def flush() -> None:
        if buf:
            body = "\n".join(line for _, line in buf).strip()
            if body:
                out.append((buf[0][0], buf[-1][0], body))

    for number, raw in enumerate(lines, start=1):
        # Очень длинные строки (минифицированный код) режем жёстко.
        pieces = [raw[i : i + size] for i in range(0, len(raw), size)] or [""]
        for line in pieces:
            if length + len(line) > size and buf:
                flush()
                buf, length = buf[-2:], sum(len(x) + 1 for _, x in buf[-2:])
            buf.append((number, line))
            length += len(line) + 1
    flush()
    return out[:MAX_CHUNKS_PER_FILE]


def issue_pieces(issues: list[Issue], size: int) -> list[Piece]:
    pieces: list[Piece] = []
    for issue in issues:
        kind = "pr" if issue.is_pr else "issue"
        header = f"{'PR' if issue.is_pr else 'Issue'} #{issue.number} ({issue.state}): {issue.title}"
        body = (header + "\n\n" + issue.body).strip()
        if has_secret(body):
            continue
        for _, _, part in chunk_text(body, size)[:5]:
            pieces.append(
                Piece(f"{kind}s/{issue.number}", kind, part, meta={"url": issue.url, "number": issue.number})
            )
    return pieces


async def _download(
    github: GitHubClient, owner: str, name: str, token: str | None, entries: list[TreeEntry]
) -> dict[str, str]:
    """Тексты разрешённых файлов; бинарные и с секретами пропускаются."""
    semaphore = asyncio.Semaphore(BLOB_CONCURRENCY)
    texts: dict[str, str] = {}

    async def one(entry: TreeEntry) -> None:
        async with semaphore:
            data = await github.get_blob(owner, name, entry.sha, token)
        text = decode_text(data)
        if text is None or not text.strip() or has_secret(text):
            return
        texts[entry.path] = text

    await asyncio.gather(*(one(e) for e in entries))
    return texts


@dataclass
class IndexResult:
    commit: str
    files: int
    skipped: int
    changed: bool


async def index_repository(
    sessions: async_sessionmaker[AsyncSession],
    github: GitHubClient,
    embeddings: EmbeddingProvider,
    repo_id: int,
    *,
    incremental: bool,
) -> IndexResult:
    settings = get_settings()
    async with sessions() as s:
        repo = await s.get(Repository, repo_id)
        if repo is None:
            raise LookupError("repo gone")
        owner, name = repo.owner, repo.name
        token = decrypt_secret(repo.github_token_encrypted) if repo.github_token_encrypted else None
        branch = repo.default_branch or "main"
        active_id = repo.active_index_id
        active = await s.get(IndexVersion, active_id) if active_id else None
        base_sha = active.commit_sha if active else None

    head = await github.head_commit(owner, name, branch, token)
    if base_sha == head.sha:
        return IndexResult(head.sha, repo.indexed_files, repo.skipped_files, changed=False)

    tree = await github.list_tree(owner, name, head.sha, token)
    skipped = 0
    allowed: list[TreeEntry] = []
    for entry in tree:
        if skip_reason(entry.path, entry.size):
            skipped += 1
        else:
            allowed.append(entry)
    allowed = allowed[: settings.max_repo_files]

    # Какие файлы пересчитывать, а какие взять из прошлой версии.
    keep_from_old: set[str] | None = None
    to_read = allowed
    if incremental and active is not None and base_sha:
        changes = await github.compare(owner, name, base_sha, head.sha, token)
        if changes is not None:
            changed_paths = _changed_paths(changes)
            to_read = [e for e in allowed if e.path in changed_paths]
            keep_from_old = {e.path for e in allowed} - changed_paths

    texts = await _download(github, owner, name, token, to_read)
    skipped += len(to_read) - len(texts)

    pieces: list[Piece] = []
    commit_meta = {"author": head.author, "date": head.date}
    for path, text in texts.items():
        kind = file_kind(path)
        for start, end, body in chunk_text(text, settings.index_chunk_chars):
            pieces.append(Piece(path, kind, body, start, end, dict(commit_meta)))
    issues = await github.list_issues(owner, name, token, settings.index_issue_pages)
    pieces.extend(issue_pieces(issues, settings.index_chunk_chars))

    vectors = await embeddings.embed([f"{p.path}\n{p.text}"[:EMBED_TEXT_CHARS] for p in pieces])

    async with sessions() as s, s.begin():
        version = IndexVersion(repo_id=repo_id, commit_sha=head.sha, status="building")
        s.add(version)
        await s.flush()
        rows = [
            {
                "repo_id": repo_id,
                "index_version_id": version.id,
                "path": p.path,
                "kind": p.kind,
                "text": p.text,
                "start_line": p.start_line,
                "end_line": p.end_line,
                "commit_sha": head.sha,
                "meta": p.meta,
                "embedding": vec,
            }
            for p, vec in zip(pieces, vectors, strict=True)
        ]
        for i in range(0, len(rows), 500):
            await s.execute(insert(Chunk), rows[i : i + 500])

        if keep_from_old is not None and active is not None:
            old = await s.scalars(
                select(Chunk).where(
                    Chunk.index_version_id == active.id,
                    Chunk.path.in_(keep_from_old),
                    Chunk.kind.in_(("code", "doc", "config")),
                )
            )
            copies = [
                {
                    "repo_id": repo_id,
                    "index_version_id": version.id,
                    "path": c.path,
                    "kind": c.kind,
                    "text": c.text,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "commit_sha": head.sha,
                    "meta": c.meta,
                    "embedding": c.embedding,
                }
                for c in old
            ]
            for i in range(0, len(copies), 500):
                await s.execute(insert(Chunk), copies[i : i + 500])

        file_count = len(
            (
                await s.execute(
                    select(Chunk.path).where(
                        Chunk.index_version_id == version.id, Chunk.kind.in_(("code", "doc", "config"))
                    ).distinct()
                )
            ).all()
        )
        version.status = "ready"
        # Атомарное переключение: после коммита все ответы идут по новой версии.
        await s.execute(
            update(Repository)
            .where(Repository.id == repo_id)
            .values(
                active_index_id=version.id,
                last_commit=head.sha,
                status="ready",
                last_error=None,
                indexed_files=file_count,
                skipped_files=skipped,
            )
        )
        stale = (
            await s.scalars(
                select(IndexVersion.id).where(
                    IndexVersion.repo_id == repo_id, IndexVersion.id != version.id
                )
            )
        ).all()
        if stale:
            await s.execute(delete(Chunk).where(Chunk.index_version_id.in_(stale)))
            await s.execute(delete(IndexVersion).where(IndexVersion.id.in_(stale)))
    log.info("index ready: repo=%s files=%s skipped=%s", repo_id, file_count, skipped)
    return IndexResult(head.sha, file_count, skipped, changed=True)


def _changed_paths(changes: list[ChangedFile]) -> set[str]:
    """Пути, чьи старые фрагменты нужно выбросить (изменены, удалены, переименованы)."""
    paths: set[str] = set()
    for change in changes:
        paths.add(change.path)
        if change.previous_path:
            paths.add(change.previous_path)
    return paths
