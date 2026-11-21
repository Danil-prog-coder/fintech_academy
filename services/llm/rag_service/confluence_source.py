"""Confluence as a knowledge source: receiver of the adapter's change batches (Docs/contract/confluence-batches.md).

The adapter (llm/integrations/confluence) reads Confluence and sends `POST /sources/{source_id}/batches`; this module
applies a batch to the source's local copy and starts a reindex of the source's project:

- only allowlisted sources are accepted (`CONFLUENCE_SOURCES`: JSON `{source_id: {"project_id": ...}}`); the project
  comes from that trusted configuration, never from the caller's payload;
- idempotent on `batch_id` (a repeated batch returns the original receipt), ordered on `source_sequence` (a stale
  batch — sequence not newer than the applied one — is acknowledged and never applied);
- deletes / revocations (`deleted=true`: deleted, visibility_revoked, unpublished) remove only that source's copy of
  that document; uploads, Git documents and other sources are never touched;
- a page is stored as Markdown converted from its storage HTML (tables, code macros and filter examples verbatim) with
  its Confluence link; PDF / DOCX / Markdown attachments are stored as files of the same page and indexed too;
- indexing reads the stored copies like Git documents (`local_files`), so every chunk cites the Confluence page URL.

A reindex always reads the newest stored copies, so a job of an older batch that finishes late still publishes the
current state (activation never rolls a source back). State lives in STATE_DIR/confluence.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import re
import threading
from contextlib import contextmanager
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from filelock import FileLock

from .config import get_settings
from .ingest.util import slugify

log = logging.getLogger(__name__)
_lock = threading.RLock()
_file_locks: dict[str, FileLock] = {}
ATTACHMENT_EXT = {".pdf", ".docx", ".md", ".txt"}
IMAGE_EXT = {".png", ".jpg", ".jpeg"}
MAX_RECEIPTS = 500


class BatchError(ValueError):
    """Bad payload: HTTP 400. `unknown_source` → 422."""

    def __init__(self, message: str, *, unknown_source: bool = False) -> None:
        super().__init__(message)
        self.unknown_source = unknown_source


# ------------------------------------------------------------------ configuration and state

def allowed_sources() -> dict[str, dict]:
    raw = (get_settings().confluence_sources or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.error("CONFLUENCE_SOURCES is not valid JSON: Confluence batches are rejected")
        return {}
    if not isinstance(data, dict):
        return {}
    static = {str(k): v for k, v in data.items() if isinstance(v, dict) and v.get("project_id")}
    with _source_guard():
        path = _root() / "registered-sources.json"
        registered = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for source_id, item in registered.items():
        template = static.get(item.get("template_source_id"))
        if (template and template.get("project_id") == item.get("project_id")
                and item.get("template_config_hash") == _config_hash(template) and source_id not in static):
            static[source_id] = item
    return static


def _config_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def register_managed_source(project_id: str, item: dict) -> dict:
    """Persist a server-verified source under an existing configured template."""
    source_id = item.get("source_id") or ""
    if (not re.fullmatch(r"managed-[0-9a-f]{24}", source_id) or item.get("project_id") != project_id
            or item.get("managed") is not True):
        raise BatchError("invalid managed source identity")
    if not re.fullmatch(r"[0-9]{1,32}", str(item.get("root_page_id") or "")):
        raise BatchError("invalid managed source page")
    for field in ("source_binding", "template_binding"):
        if not re.fullmatch(r"[0-9a-f]{32}", str(item.get(field) or "")):
            raise BatchError("invalid managed source binding")
    static = json.loads(get_settings().confluence_sources or "{}")
    template = static.get(item.get("template_source_id"))
    if not template or template.get("project_id") != project_id:
        raise BatchError("source template is not configured for this project")
    if template.get("space_id") and str(template["space_id"]) != str(item.get("space_id")):
        raise BatchError("source does not belong to the configured space")
    fields = ("source_id", "project_id", "space_id", "root_page_id", "section", "include_children",
              "source_binding", "template_source_id", "template_binding", "page_url", "managed")
    item = {field: item.get(field) for field in fields}
    item["template_config_hash"] = _config_hash(template)
    with _source_guard():
        path = _root() / "registered-sources.json"
        registered = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if source_id in registered and registered[source_id] != item:
            raise BatchError("source identity already has a different binding")
        registered[source_id] = item
        _atomic_json(path, registered)
    return item


def _root() -> Path:
    return Path(get_settings().state_dir) / "confluence"


def _state_file() -> Path:
    return _root() / "state.json"


@contextmanager
def _source_guard():
    # A single manifest contains all sources; lock the whole state, also across workers.
    with _lock:
        root = _root()
        root.mkdir(parents=True, exist_ok=True)
        key = str(root.resolve())
        lock = _file_locks.setdefault(key, FileLock(str(root / ".manifest.lock")))
        with lock:
            yield


def _load() -> dict:
    p = _state_file()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save(state: dict) -> None:
    _atomic_json(_state_file(), state)


def _atomic_json(p: Path, state: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as output:
        output.write(json.dumps(state, ensure_ascii=False, indent=1))
        output.flush()
        os.fsync(output.fileno())
    tmp.replace(p)


def _source_dir(source_id: str) -> Path:
    return _root() / slugify(source_id)


# ------------------------------------------------------------------ storage HTML → Markdown

class _Storage2Md(HTMLParser):
    """Confluence storage format → Markdown: headings, paragraphs, lists, tables, code macros. Text is kept verbatim."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.buf: list[str] = []
        self.lists: list[str] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.code: list[str] | None = None
        self.macro: list[str] = []
        self.heading = 0
        self.skip = 0

    def _text(self) -> list[str]:
        if self.code is not None:
            return self.code
        if self.cell is not None:
            return self.cell
        return self.buf

    def _flush(self, prefix: str = "") -> None:
        text = re.sub(r"[ \t]+", " ", "".join(self.buf)).strip()
        self.buf = []
        if text:
            self.out.append(prefix + text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "ac:structured-macro":
            name = a.get("ac:name") or ""
            self.macro.append(name)
            if name in ("code", "noformat"):
                self._flush()
                self.code = []
            return
        if tag in ("ac:image", "ri:attachment", "ac:parameter") or self.skip:
            if tag in ("ac:image", "ac:parameter"):
                self.skip += 1
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self.heading = int(tag[1])
        elif tag in ("p", "div"):
            if self.table is None:
                self._flush()
        elif tag == "br":
            self._text().append("\n" if self.code is not None else " ")
        elif tag in ("ul", "ol"):
            self._flush()
            self.lists.append(tag)
        elif tag == "li":
            self._flush()
        elif tag == "table":
            self._flush()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "ac:structured-macro":
            name = self.macro.pop() if self.macro else ""
            if name in ("code", "noformat") and self.code is not None:
                body = "".join(self.code).strip("\n")
                self.code = None
                self.out.append(f"```\n{body}\n```")
            return
        if tag in ("ac:image", "ac:parameter"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._flush("#" * (self.heading or 2) + " ")
            self.heading = 0
        elif tag in ("p", "div") and self.table is None:
            self._flush()
        elif tag == "li":
            marker = "1." if self.lists and self.lists[-1] == "ol" else "-"
            self._flush("  " * max(0, len(self.lists) - 1) + marker + " ")
        elif tag in ("ul", "ol") and self.lists:
            self._flush()
            self.lists.pop()
        elif tag in ("td", "th") and self.row is not None and self.cell is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip().replace("|", "\\|"))
            self.cell = None
        elif tag == "tr" and self.table is not None and self.row is not None:
            if any(self.row):
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            rows, self.table = self.table, None
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                self.out.append("\n".join(lines))

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        self._text().append(data)

    def unknown_decl(self, data: str) -> None:  # <![CDATA[ … ]]> of code macros
        if data.upper().startswith("CDATA["):
            self._text().append(data[6:])

    def markdown(self) -> str:
        self._flush()
        return "\n\n".join(self.out).strip() + "\n"


def storage_to_markdown(html: str) -> str:
    parser = _Storage2Md()
    parser.feed(html or "")
    parser.close()
    return parser.markdown()


def _page_markdown(doc: dict) -> str:
    title = (doc.get("title") or "").strip() or f"Страница {doc.get('page_id')}"
    body = storage_to_markdown(doc.get("content_html") or "")
    if not body.strip() and doc.get("content_text"):
        body = unescape(str(doc["content_text"])).strip() + "\n"
    return f"# {title}\n\n{body}"


# ------------------------------------------------------------------ batches

def _validate(source_id: str, body: dict) -> tuple[dict, int]:
    if not isinstance(body, dict):
        raise BatchError("payload must be a JSON object")
    if str(body.get("source_id")) != source_id:
        raise BatchError("source_id in the path and in the body differ")
    if not body.get("batch_id") or not isinstance(body.get("documents"), list):
        raise BatchError("batch_id and documents are required")
    if not body.get("source_binding"):
        raise BatchError("source_binding is required (legacy payloads are unsafe)")
    try:
        seq = int(body.get("source_sequence"))
    except (TypeError, ValueError):
        raise BatchError("source_sequence must be an integer") from None
    if type(body.get("source_sequence")) is not int or seq < 1:
        raise BatchError("source_sequence must be a positive integer")
    src = allowed_sources().get(source_id)
    if src is None:
        raise BatchError(f"unknown source {source_id}", unknown_source=True)
    if src.get("source_binding") and src["source_binding"] != body["source_binding"]:
        raise BatchError("source binding differs from configured binding")
    seen = set()
    for doc in body["documents"]:
        if not isinstance(doc, dict):
            raise BatchError("each document must be an object")
        page = str(doc.get("page_id") or "")
        if not re.fullmatch(r"[0-9]{1,32}", page) or doc.get("document_id") != f"{source_id}:page:{page}":
            raise BatchError("document_id/page_id must belong to this source")
        if page in seen:
            raise BatchError("duplicate page in batch")
        seen.add(page)
        if src.get("space_id") and str(doc.get("space_id")) != str(src["space_id"]):
            raise BatchError("document belongs to a different space")
        if type(doc.get("deleted", False)) is not bool:
            raise BatchError("deleted must be boolean")
        for field in ("title", "content_html", "content_text", "source_url"):
            if field in doc and not isinstance(doc[field], str):
                raise BatchError(f"{field} must be text")
        attachments = doc.get("attachments") or []
        if not isinstance(attachments, list) or any(not isinstance(a, dict) for a in attachments):
            raise BatchError("attachments must be a list of objects")
    return src, seq


def _apply_document(base: Path, docs: dict, doc: dict) -> None:
    doc_key = str(doc.get("document_id") or "")
    if not doc_key:
        raise BatchError("document_id is required")
    if doc.get("deleted"):
        docs.pop(doc_key, None)
        return
    # Immutable version directories keep previous committed files valid if preparation fails.
    page_dir = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
    target = base / page_dir
    target.mkdir(parents=True, exist_ok=True)
    files = {"page.md": {"title": doc.get("title") or "", "kind": "page"}}
    (target / "page.md").write_text(_page_markdown(doc), encoding="utf-8")
    (target / "page.storage").write_text(doc.get("content_html") or "", encoding="utf-8")
    images = {}
    image_hashes = {}
    for att in doc.get("attachments") or []:
        name = Path(str(att.get("filename") or "")).name
        ext = Path(name).suffix.lower()
        if not att.get("has_data") or ext not in ATTACHMENT_EXT | IMAGE_EXT:
            continue
        data = base64.b64decode(att.get("content_base64") or "", validate=True)
        if att.get("sha256") and hashlib.sha256(data).hexdigest() != att["sha256"]:
            raise BatchError(f"sha256 mismatch for attachment of {doc_key}")
        fname = f"{slugify(str(att.get('attachment_id') or ''))}-{name}"
        (target / fname).write_bytes(data)
        if ext in IMAGE_EXT:
            images[name] = fname
            image_hashes[name] = hashlib.sha256(data).hexdigest()
        else:
            files[fname] = {"title": name, "kind": "attachment", "version": att.get("version"),
                            "fingerprint": _config_hash({"sha256": hashlib.sha256(data).hexdigest(),
                                "filename": name, "version": att.get("version"),
                                "page_title": doc.get("title"), "source_url": doc.get("source_url")})}
    files["page.md"]["fingerprint"] = _config_hash({
        key: doc.get(key) for key in ("title", "version", "source_url", "content_html", "content_text")
    } | {"images": image_hashes})
    docs[doc_key] = {"dir": page_dir, "files": files, "title": doc.get("title") or "",
                     "source_url": doc.get("source_url") or "", "version": doc.get("version"),
                     "page_id": str(doc.get("page_id") or ""), "images": images,
                     "storage_file": "page.storage" if doc.get("content_html") else None,
                     "fingerprint": page_dir}


def receive_batch(source_id: str, body: dict, start_job=None) -> dict:
    """Import a batch to staging. An optional legacy callback can start indexing explicitly."""
    src, seq = _validate(source_id, body)
    batch_id = str(body["batch_id"])
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    with _source_guard():
        state = _load()
        st = state.setdefault(source_id, {"applied_sequence": 0, "receipts": {}, "documents": {}})
        if st.get("source_binding") and st["source_binding"] != body["source_binding"]:
            raise BatchError("source binding changed; an explicit source migration is required")
        if batch_id in st["receipts"]:
            previous_hash = st.get("payload_hashes", {}).get(batch_id)
            if previous_hash and previous_hash != digest:
                raise BatchError("batch_id reused with different content")
            return st["receipts"][batch_id]
        if seq <= int(st.get("applied_sequence") or 0):
            receipt = {"batch_id": batch_id, "accepted": True, "job_id": None, "message": "stale"}
            return receipt
        base = _source_dir(source_id)
        base.mkdir(parents=True, exist_ok=True)
        docs = dict(st["documents"])
        try:
            for doc in body["documents"]:
                if not isinstance(doc, dict):
                    raise BatchError("each document must be an object")
                _apply_document(base, docs, doc)
        except (binascii.Error, ValueError, TypeError) as error:
            raise BatchError("invalid document or attachment") from error
        st["documents"] = docs
        st["source_binding"] = body["source_binding"]
        st["applied_sequence"] = seq
        st["project_id"] = src["project_id"]
        # Persist before launching: the indexing worker may read local_files immediately.
        # If starting the job fails, restore the manifest so the adapter can safely retry.
        job_id = None
        if start_job:
            previous_state = _load()
            _save(state)
            try:
                job_id = start_job(src["project_id"])
            except Exception:
                _save(previous_state)
                raise
        receipt = {"batch_id": batch_id, "accepted": True, "job_id": job_id,
                   "message": "" if start_job else "staged; awaiting explicit publication"}
        st["receipts"][batch_id] = receipt
        st.setdefault("payload_hashes", {})[batch_id] = digest
        while len(st["receipts"]) > MAX_RECEIPTS:
            expired = next(iter(st["receipts"]))
            st["receipts"].pop(expired)
            st["payload_hashes"].pop(expired, None)
        _save(state)
        return receipt


def local_files(project_id: str) -> list[tuple[Path, dict]]:
    """Stored Confluence pages and attachments of the project's allowlisted sources, with their metadata."""
    allowed = allowed_sources()
    out: list[tuple[Path, dict]] = []
    with _source_guard():
        state = _load()
    for source_id, st in state.items():
        if allowed.get(source_id, {}).get("project_id") != project_id:
            continue
        base = _source_dir(source_id)
        for doc_key, d in (st.get("documents") or {}).items():
            for fname, info in d.get("files", {}).items():
                p = base / d["dir"] / fname
                if not p.exists():
                    raise BatchError("stored Confluence file is missing; refusing incomplete index")
                title = d.get("title") or info.get("title") or fname
                rel = f"{title}.md" if info.get("kind") == "page" else f"{title}/{info.get('title') or fname}"
                out.append((p, {
                    "source_type": "confluence", "source_id": source_id, "path": rel,
                    "doc_id": slugify(f"{doc_key}-{fname}")[:120], "url": d.get("source_url") or None,
                    "commit": str((info.get("version") or info.get("fingerprint") or "")
                                  if info.get("kind") == "attachment" else d.get("version") or ""),
                    "confluence_fingerprint": info.get("fingerprint") or d.get("fingerprint") or hashlib.sha256(p.read_bytes()).hexdigest(),
                    "confluence_title": d.get("title") or "",
                    "confluence_storage": str(base / d["dir"] / d["storage_file"])
                    if info.get("kind") == "page" and d.get("storage_file") else None,
                    "confluence_images": {name: str(base / d["dir"] / image)
                                          for name, image in d.get("images", {}).items()},
                }))
    return out


def staging_status(project_id: str, manifest: dict) -> dict:
    """Compare stored source documents to the actual published manifest, also after restarts."""
    published = {d["doc_id"]: d for d in manifest.get("documents", [])
                 if d.get("source_type") == "confluence"}
    changes = []
    current = set()
    for path, meta in local_files(project_id):
        doc_id = meta["doc_id"]
        current.add(doc_id)
        previous = published.get(doc_id)
        if previous and previous.get("confluence_fingerprint") == meta["confluence_fingerprint"]:
            continue
        changes.append({"doc_id": doc_id, "source_id": meta["source_id"],
                        "title": meta["confluence_title"], "file": meta["path"],
                        "source_url": meta.get("url"), "bytes": path.stat().st_size,
                        "change": "updated" if previous else "added"})
    for doc_id, previous in published.items():
        if doc_id not in current:
            changes.append({"doc_id": doc_id,
                            "source_id": (previous.get("git") or {}).get("source_id"),
                            "title": previous.get("title"), "file": previous.get("file"),
                            "source_url": (previous.get("git") or {}).get("url"),
                            "bytes": 0, "change": "removed"})
    return {"project_id": project_id, "active_generation": manifest.get("generation"),
            "has_changes": bool(changes), "documents": changes, "count": len(changes),
            "bytes": sum(item["bytes"] for item in changes)}


def denied_documents(project_id: str, manifest: dict) -> set[str]:
    """Live visibility overlay; a tombstone or removed scope takes effect before publication.

    Derive IDs from the persisted receiver state, not an in-process cache. Ordinary updates
    keep stable IDs visible in their previously published version until explicit publication.
    Missing receiver state/configuration fails closed for Confluence only.
    """
    published = [d for d in manifest.get("documents", []) if d.get("source_type") == "confluence"]
    if not published:
        return set()
    allowed = allowed_sources()
    with _source_guard():
        state = _load()
    visible = set()
    for source_id, src in allowed.items():
        st = state.get(source_id, {})
        if src.get("project_id") != project_id or st.get("project_id") != project_id:
            continue
        if src.get("source_binding") and src["source_binding"] != st.get("source_binding"):
            continue
        for doc_key, doc in st.get("documents", {}).items():
            visible.update(slugify(f"{doc_key}-{fname}")[:120] for fname in doc.get("files", {}))
    return {d["doc_id"] for d in published if d["doc_id"] not in visible}


def contract_job(job: dict) -> dict:
    """RAG job → the adapter's job shape (pending | running | done | error, message)."""
    status = {"queued": "pending", "running": "running", "done": "done"}.get(job.get("status"), "error")
    return {"job_id": job.get("job_id"), "status": status, "message": "" if status != "error" else
            str(job.get("error") or job.get("note") or job.get("status") or "")[:200]}
