"""Git repositories as a knowledge source (FR-GIT-01..05, 07): registry + full / incremental synchronisation.

A source = provider (github | gitlab, self-hosted GitLab by base URL), repo, branch, include / exclude glob patterns
and the NAME of an env variable with a read-only token (FR-GIT-07: the token itself is never stored in the registry,
returned by the API or logged). Files are downloaded to STATE_DIR/git/<source_id>/files/<path> and indexed by the
same pipeline as uploads (FR-ING-01..08). Every document keeps source_type=git, provider, repo, branch, path and
the commit SHA (document_version); chunks carry a link to the file pinned to that SHA with a heading anchor (FR-GIT-02).

Sync (FR-GIT-03): webhook / polling / manual. The provider's compare API gives the diff between the last indexed
commit and the new head; only added / modified files are parsed and embedded, fragments of removed / renamed
files are dropped, everything else is copied from the active generation, and the new generation is published
atomically. On any error the current generation stays active (FR-GIT-07).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import threading
import time
import uuid
from pathlib import Path, PurePosixPath

from ..config import get_settings
from ..ingest.util import slugify
from .providers import Change, GitError, make_provider

log = logging.getLogger(__name__)
DOC_EXT = {".md", ".markdown", ".txt", ".docx", ".pdf"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
DEFAULT_INCLUDE = ["**/*.md", "**/*.markdown", "**/*.txt", "**/*.docx", "**/*.pdf"]
_lock = threading.RLock()


def glob_to_regex(pattern: str) -> re.Pattern:
    """`docs/**/*.md` style patterns: `**/` = any folders (or none), `*` = within one segment."""
    i, out = 0, ""
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(f"^{out}$")


def matches(path: str, include: list[str], exclude: list[str]) -> bool:
    if not any(glob_to_regex(p).match(path) for p in include or DEFAULT_INCLUDE):
        return False
    return not any(glob_to_regex(p).match(path) for p in exclude or [])


def git_doc_id(source_id: str, path: str) -> str:
    stem = str(PurePosixPath(path).with_suffix(""))
    return f"git_{slugify(f'{source_id}_{stem}', 36)}_{hashlib.sha1(path.encode()).hexdigest()[:6]}"


# ------------------------------------------------------------------ registry
def _root() -> Path:
    p = Path(get_settings().state_dir) / "git"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _reg_file() -> Path:
    return _root() / "sources.json"


def load_all() -> dict[str, dict]:
    f = _reg_file()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _save_all(d: dict) -> None:
    tmp = _reg_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)  # contains webhook secrets
    tmp.replace(_reg_file())


def public_view(src: dict, with_secret: bool = False) -> dict:
    s = get_settings()
    out = {k: v for k, v in src.items() if k not in ("webhook_secret", "files")}
    out["files_indexed"] = len(src.get("files") or {})
    out["token_configured"] = bool(src.get("token_env") and os.environ.get(src["token_env"]))
    out["webhook"] = {"url": f"{s.public_base_url.rstrip('/')}/webhooks/{src['provider']}",
                      "header": "X-Hub-Signature-256 (HMAC-SHA256)" if src["provider"] == "github" else "X-Gitlab-Token",
                      "events": "push", **({"secret": src.get("webhook_secret")} if with_secret else {})}
    return out


def get(source_id: str) -> dict | None:
    return load_all().get(source_id)


def add(project_id: str, provider: str, repo: str, branch: str = "main", *, base_url: str | None = None,
        include: list[str] | None = None, exclude: list[str] | None = None, token_env: str | None = None) -> dict:
    if provider not in ("github", "gitlab"):
        raise ValueError("provider: github | gitlab")
    if token_env and not re.fullmatch(r"[A-Z][A-Z0-9_]{2,64}", token_env):
        raise ValueError("token_env must be an env variable NAME (the token itself goes to .env)")
    src = {"id": uuid.uuid4().hex[:10], "project_id": project_id, "provider": provider, "repo": repo.strip("/"),
           "branch": branch, "base_url": base_url, "include": include or DEFAULT_INCLUDE, "exclude": exclude or [],
           "token_env": token_env, "webhook_secret": secrets.token_hex(20), "enabled": True, "created_at": time.time(),
           "indexed_sha": None, "last_sync": None, "files": {}}
    with _lock:
        d = load_all()
        d[src["id"]] = src
        _save_all(d)
    return src


def update(source_id: str, **changes) -> dict | None:
    allowed = {"branch", "include", "exclude", "token_env", "enabled", "base_url"}
    with _lock:
        d = load_all()
        src = d.get(source_id)
        if not src:
            return None
        if changes.get("token_env") and not re.fullmatch(r"[A-Z][A-Z0-9_]{2,64}", changes["token_env"]):
            raise ValueError("token_env must be an env variable NAME")
        if "branch" in changes and changes["branch"] != src["branch"]:
            src["indexed_sha"] = None  # another branch → full import on next sync
        src.update({k: v for k, v in changes.items() if k in allowed and v is not None})
        _save_all(d)
        return src


def _token(src: dict) -> str | None:
    return os.environ.get(src["token_env"]) if src.get("token_env") else None


def provider_for(src: dict):
    return make_provider(src, _token(src))


def check_access(source_id: str) -> dict:
    src = get(source_id)
    if not src:
        raise KeyError(source_id)
    try:
        p = provider_for(src)
        info = p.check_access()
        info["head"] = p.head()
        if info.get("can_push"):
            info["warning"] = "токен даёт права на запись — для бота достаточно read-only (FR-GIT-07)"
        return info
    except GitError as e:
        return {"ok": False, "error": str(e)}


def local_files(project_id: str) -> list[tuple[Path, dict]]:
    """Downloaded documents of all enabled sources of the project with their git metadata (for a full reindex)."""
    out = []
    for src in load_all().values():
        if src.get("project_id") != project_id or not src.get("enabled"):
            continue
        base = _root() / src["id"] / "files"
        for path, info in (src.get("files") or {}).items():
            p = base / path
            if p.exists():
                out.append((p, file_meta(src, path, info.get("commit") or src.get("indexed_sha") or "")))
    return out


def file_meta(src: dict, path: str, commit: str) -> dict:
    prov = provider_for(src)
    return {"source_type": "git", "source_id": src["id"], "provider": src["provider"], "repo": src["repo"],
            "branch": src["branch"], "path": path, "commit": commit, "doc_id": git_doc_id(src["id"], path),
            "url": prov.blob_url(commit, path) if commit else None,
            "url_template": prov.blob_url(commit, path, anchor="{anchor}") if commit else None}


# ------------------------------------------------------------------ webhooks (FR-GIT-03, FR-GIT-07)
def verify_github(secret: str, body: bytes, signature: str | None) -> bool:
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + mac, signature)


def verify_gitlab(secret: str, token: str | None) -> bool:
    return bool(secret and token and hmac.compare_digest(secret, token))


def sources_for_push(provider: str, repo: str, ref: str) -> list[dict]:
    branch = ref.removeprefix("refs/heads/")
    return [s for s in load_all().values() if s["provider"] == provider and s.get("enabled")
            and s["repo"].lower() == repo.lower() and s["branch"] == branch]


# ------------------------------------------------------------------ sync
def _referenced_images(md_text: str, md_path: str) -> set[str]:
    out = set()
    for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)", md_text):
        src = m.group(1)
        if src.startswith(("http://", "https://", "data:")):
            continue
        p = PurePosixPath(md_path).parent / src.split("#")[0]
        parts: list[str] = []
        for part in p.parts:
            if part == "..":
                if parts:
                    parts.pop()
            elif part != ".":
                parts.append(part)
        out.add("/".join(parts))
    return out


def plan_changes(src: dict, tree: dict[str, int], changes: list[Change] | None) -> tuple[set[str], set[str], list[dict]]:
    """→ (to_index, to_remove, skipped). `changes=None` means a full import."""
    s = get_settings()
    skipped = []
    wanted = {}
    for path, size in sorted(tree.items()):
        if PurePosixPath(path).suffix.lower() not in DOC_EXT or not matches(path, src["include"], src["exclude"]):
            continue
        if size and size > s.git_max_file_bytes:
            skipped.append({"path": path, "why": f"больше лимита {s.git_max_file_bytes} байт"})
            continue
        wanted[path] = size
    if len(wanted) > s.git_max_files:
        for path in list(wanted)[s.git_max_files:]:
            skipped.append({"path": path, "why": f"превышен лимит {s.git_max_files} файлов за импорт"})
            wanted.pop(path)
    indexed = set((src.get("files") or {}).keys())
    if changes is None:
        return set(wanted), indexed - set(wanted), skipped
    to_index: set[str] = set()
    to_remove: set[str] = set()
    for c in changes:
        if c.status == "removed":
            to_remove.add(c.path)
            continue
        if c.status == "renamed" and c.previous_path:
            to_remove.add(c.previous_path)
        if c.path in wanted:
            to_index.add(c.path)
    to_index |= set(wanted) - indexed  # patterns changed → newly matching files
    to_remove |= indexed - set(wanted)  # no longer matching (or deleted)
    return to_index, to_remove & indexed, skipped


def sync(source_id: str, *, full: bool = False, describe: bool = True) -> dict:
    from ..faq import get_faq
    from ..index import store
    from ..ingest.pipeline import ingest, ingest_incremental

    src = get(source_id)
    if not src:
        raise KeyError(source_id)
    t0 = time.time()
    rep: dict = {"source_id": source_id, "repo": src["repo"], "branch": src["branch"], "started_at": t0}
    try:
        prov = provider_for(src)
        head = prov.head()
        rep["commit"] = head
        if not full and src.get("indexed_sha") == head:
            rep.update(status="up_to_date", added=0, modified=0, removed=0)
            return _record(source_id, rep, None)
        listing = prov.list_files(head)
        tree = {f.path: f.size for f in listing}
        changes = None
        if not full and src.get("indexed_sha"):
            try:
                changes = prov.compare(src["indexed_sha"], head)
                rep["mode"] = "incremental"
            except GitError as e:
                log.warning("compare failed (%s) — full import", e)
                rep["mode"] = "full (compare failed)"
        else:
            rep["mode"] = "full"
        to_index, to_remove, skipped = plan_changes(src, tree, changes)
        prev = set((src.get("files") or {}).keys())
        rep.update(added=len(to_index - prev), modified=len(to_index & prev), removed=len(to_remove), skipped=skipped)
        base = _root() / source_id / "files"
        downloaded: dict[str, bytes] = {}
        for path in sorted(to_index):
            downloaded[path] = prov.fetch(head, path)
        images = set()
        for path, data in downloaded.items():
            if PurePosixPath(path).suffix.lower() in (".md", ".markdown"):
                images |= {i for i in _referenced_images(data.decode("utf-8", "replace"), path)
                           if i in tree and PurePosixPath(i).suffix.lower() in IMG_EXT}
        for img in sorted(images):
            if (tree.get(img) or 0) <= get_settings().git_max_file_bytes:
                downloaded[img] = prov.fetch(head, img)
        # the local copy is updated before indexing; the knowledge base switches only if indexing succeeds (FR-GIT-07).
        # If it fails, indexed_sha stays the same, so the next sync re-processes these files.
        for path, data in downloaded.items():
            p = base / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        new_files = {p: {"commit": head, "size": len(downloaded[p])} for p in to_index}
        project_id = src["project_id"]
        removed_ids = {git_doc_id(source_id, p) for p in to_remove}
        files_meta = [(base / p, file_meta(src, p, head)) for p in sorted(to_index)]
        before = store.active_manifest(project_id)  # FR-ADM-05: what changed, for «Документация обновлена»
        if store.active_generation(project_id):
            ir = ingest_incremental(project_id, files_meta, removed_ids, describe=describe)
        else:
            others = [(f, m) for f, m in local_files(project_id) if m["source_id"] != source_id]
            ir = ingest([get_settings().kb_dir], project_id, describe=describe, extra_files=others + files_meta, include_git=False)
        if ir.get("status") != "ok":
            raise GitError(f"indexing failed: {ir.get('reason') or ir.get('errors')}")
        for p in to_remove:
            (base / p).unlink(missing_ok=True)
        files = dict(src.get("files") or {})
        for p in to_remove:
            files.pop(p, None)
        files.update(new_files)
        rep.update(status="ok", generation=ir.get("generation"), indexing={k: ir.get(k) for k in ("counts", "incremental", "elapsed_s")},
                   errors=ir.get("errors") or [])
        try:
            from .. import notify

            rep["changes"] = notify.manifest_diff(before, store.active_manifest(project_id))
            rep["notified"] = notify.push_docs_updated(project_id, ir.get("generation"), f"git:{src.get('repo')}", rep["changes"])
        except Exception as e:  # noqa: BLE001
            log.warning("docs change summary failed: %s", e)
        try:
            rep["faq"] = get_faq().on_generation_change(project_id)  # FR-FAQ-05
        except Exception as e:  # noqa: BLE001
            log.warning("faq invalidation failed: %s", e)
        return _record(source_id, rep, {"indexed_sha": head, "files": files})
    except Exception as e:  # noqa: BLE001  — the active generation stays as it was
        log.exception("git sync failed")
        rep.update(status="failed", error=str(e)[:500])
        return _record(source_id, rep, None)


def _record(source_id: str, rep: dict, changes: dict | None) -> dict:
    rep["finished_at"] = time.time()
    rep["elapsed_s"] = round(rep["finished_at"] - rep.get("started_at", rep["finished_at"]), 1)
    with _lock:
        d = load_all()
        if source_id in d:
            d[source_id]["last_sync"] = {k: v for k, v in rep.items() if k not in ("faq",)}
            if changes:
                d[source_id].update(changes)
            _save_all(d)
    return rep


def remove(source_id: str) -> dict:
    """Disconnect: drop its documents from the knowledge base (new generation) and the local copy."""
    from ..index import store
    from ..ingest.pipeline import ingest_incremental

    src = get(source_id)
    if not src:
        raise KeyError(source_id)
    ids = {git_doc_id(source_id, p) for p in (src.get("files") or {})}
    rep = {"removed_docs": len(ids)}
    if ids and store.active_generation(src["project_id"]):
        ir = ingest_incremental(src["project_id"], [], ids, describe=False)
        if ir.get("status") != "ok":
            # e.g. the repository was the only content: an empty knowledge base is never published — keep the source
            return {**rep, "status": "failed", "reason": ir.get("reason") or "reindex failed"}
        rep["generation"] = ir.get("generation")
    with _lock:
        d = load_all()
        d.pop(source_id, None)
        _save_all(d)
    shutil.rmtree(_root() / source_id, ignore_errors=True)
    return {**rep, "status": "ok"}


_poller: threading.Thread | None = None


def start_poller(run_job) -> None:
    """FR-GIT-03 polling for sources behind NAT (GIT_POLL_INTERVAL_S > 0). `run_job(source_id)` queues a sync job."""
    global _poller
    every = get_settings().git_poll_interval_s
    if not every or _poller:
        return

    def loop():
        while True:
            time.sleep(every)
            for sid, src in load_all().items():
                if not src.get("enabled"):
                    continue
                try:
                    if provider_for(src).head() != src.get("indexed_sha"):
                        run_job(sid)
                except Exception as e:  # noqa: BLE001
                    log.warning("git poll %s: %s", sid, e)

    _poller = threading.Thread(target=loop, daemon=True, name="git-poller")
    _poller.start()
