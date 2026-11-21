"""Document visibility shared by retrieval, document serving and answer caches.

Two layers:
* project-wide denial (Confluence pages withdrawn upstream) — `denied_documents` of the manifest;
* request-scoped denial — documents of sections the asking member may not see. The admin service sends
  `allowed_sections` with every question; `restrict_sections()` turns it into a set of doc_ids held in a
  context variable for the duration of the turn, so every place that already honours `denied()` (hybrid search,
  get_section / list_documents tools, exact and FAQ caches, document links) applies it without extra parameters.
"""
from __future__ import annotations

import contextvars
import hashlib
from contextlib import contextmanager

from ..confluence_source import denied_documents
from ..index import store

DEFAULT_SECTION = "general"
_REQUEST_DENIED: contextvars.ContextVar[frozenset[str]] = contextvars.ContextVar("rag_request_denied", default=frozenset())


def base_denied(project_id: str, manifest: dict | None = None) -> set[str]:
    return denied_documents(project_id, manifest if manifest is not None else store.active_manifest(project_id))


def request_denied() -> frozenset[str]:
    return _REQUEST_DENIED.get()


def denied(project_id: str, manifest: dict | None = None) -> set[str]:
    return base_denied(project_id, manifest) | set(_REQUEST_DENIED.get())


def doc_section(doc: dict) -> str:
    return doc.get("section") or DEFAULT_SECTION


def denied_for_sections(project_id: str, allowed_sections: list[str] | None, manifest: dict | None = None) -> frozenset[str]:
    """doc_ids outside `allowed_sections`; None means «no restriction», an empty list hides every document."""
    if allowed_sections is None:
        return frozenset()
    allowed = set(allowed_sections)
    m = manifest if manifest is not None else store.active_manifest(project_id)
    return frozenset(d["doc_id"] for d in m.get("documents", []) if doc_section(d) not in allowed)


def set_request_denied(doc_ids: frozenset[str]) -> None:
    """Set the restriction for the rest of the current context (a turn runs inside one copied Context)."""
    _REQUEST_DENIED.set(frozenset(doc_ids))


@contextmanager
def restrict_sections(project_id: str, allowed_sections: list[str] | None):
    token = _REQUEST_DENIED.set(denied_for_sections(project_id, allowed_sections))
    try:
        yield
    finally:
        _REQUEST_DENIED.reset(token)


def revision(project_id: str) -> str:
    manifest = store.active_manifest(project_id)
    ids = {d["doc_id"] for d in manifest.get("documents", []) if d.get("source_type") == "confluence"}
    blocked = base_denied(project_id, manifest)
    # Include the published membership too: a session that was idle throughout withdrawal
    # must still lose old context after a later publication removes the withdrawn documents.
    content = [*("published:" + key for key in sorted(ids)), *("denied:" + key for key in sorted(blocked))]
    return hashlib.sha256("\n".join(content).encode()).hexdigest() if content else ""


def answer_allowed(project_id: str, answer: dict, blocked: set[str] | None = None) -> bool:
    blocked = denied(project_id) if blocked is None else blocked
    if not blocked:
        return True
    sources = answer.get("sources") or []
    # Legacy entries without document identities cannot prove that their evidence is still visible.
    if not sources:
        return False
    for source in sources:
        doc_id = source.get("doc_id")
        chunk = source.get("chunk_id") or ""
        if not doc_id and ":" in chunk:
            doc_id = chunk.rsplit(":", 1)[0]
        if not doc_id or doc_id in blocked:
            return False
    return not any(image.split("/", 1)[0] in blocked for image in answer.get("image_ids") or [])
