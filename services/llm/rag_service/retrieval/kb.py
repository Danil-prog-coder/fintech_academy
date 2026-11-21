"""In-process view of the active generation (all chunks): outline, sections, neighbours, citation lookup."""

from __future__ import annotations

import re
import threading

from rapidfuzz import fuzz, process  # MIT

from ..index import store
from ..product import get_product
from .access import base_denied, request_denied

_cache: dict[str, dict] = {}
_lock = threading.Lock()


def invalidate(project_id: str) -> None:
    with _lock:
        _cache.pop(project_id, None)


def get_kb(project_id: str) -> dict:
    """The project-wide view is cached; a turn restricted to some sections gets a filtered copy (cheap, in memory)."""
    kb = _project_kb(project_id)
    extra = request_denied() - kb["denied_docs"]
    if not extra or not kb["generation"]:
        return kb
    chunks = [c for c in kb["chunks"] if c["doc_id"] not in extra]
    manifest = kb.get("manifest") or {}
    return {
        "generation": kb["generation"],
        "chunks": chunks,
        "by_id": {c["chunk_id"]: c for c in chunks},
        "docs": {k: v for k, v in kb["docs"].items() if k not in extra},
        "images": {k: v for k, v in kb["images"].items() if k.split("/", 1)[0] not in extra},
        "manifest": dict(manifest, documents=[d for d in manifest.get("documents", []) if d["doc_id"] not in extra]),
        "denied_docs": kb["denied_docs"] | extra,
    }


def _project_kb(project_id: str) -> dict:
    gen = store.active_generation(project_id)
    manifest = store.active_manifest(project_id) if gen else {}
    blocked = base_denied(project_id, manifest)
    with _lock:
        cached = _cache.get(project_id)
        if cached and cached["generation"] == gen and cached.get("denied_docs", set()) == blocked:
            return cached
    if not gen:
        kb = {"generation": None, "chunks": [], "by_id": {}, "docs": {}, "images": {}}
    else:
        chunks = sorted((c for c in store.scroll_all(project_id, gen) if c["doc_id"] not in blocked),
                        key=lambda p: (p["doc_id"], p["order"]))
        docs: dict[str, dict] = {}
        for c in chunks:
            d = docs.setdefault(c["doc_id"], {"doc_id": c["doc_id"], "title": c["document_title"], "sections": []})
            sp = " → ".join(c["section_path"])
            if sp and sp not in d["sections"]:
                d["sections"].append(sp)
        manifest = dict(manifest, documents=[d for d in manifest.get("documents", []) if d["doc_id"] not in blocked])
        kb = {
            "generation": gen,
            "chunks": chunks,
            "by_id": {c["chunk_id"]: c for c in chunks},
            "docs": docs,
            "images": {key: value for key, value in manifest.get("images", {}).items()
                       if key.split("/", 1)[0] not in blocked},
            "manifest": manifest,
        }
    kb["denied_docs"] = blocked
    with _lock:
        _cache[project_id] = kb
    return kb


_GENERIC = {"документ", "документа", "инструкция", "инструкции", "работы", "работа", "функциональные", "возможности", "раздел"}


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[а-яёa-z0-9]{2,}", text.lower().replace("ё", "е")) if w not in _GENERIC]


def match_document(kb: dict, name: str) -> tuple[str | None, float]:
    """Resolve a document name; every distinctive word of the query must match a title word.

    A name that shares only a generic word with a title does not resolve to it (FR-GEN-05: an object
    missing from the base must not be silently replaced by a similar one); aliases come from the product file.
    """
    if not name:
        return None, 0.0
    alias = get_product().get("aliases") or {}
    q = alias.get(name.lower().strip(), name.lower())
    qw = _words(q)
    best: tuple[str | None, float] = (None, 0.0)
    for doc_id, d in kb["docs"].items():
        tw = _words(d["title"].replace("-", " "))
        if not qw or not tw:
            continue
        hits = [max(fuzz.ratio(w[:6], t[:6]) for t in tw) for w in qw]
        if min(hits) >= 80:
            score = sum(hits) / len(hits)
            if score > best[1]:
                best = (doc_id, score)
    return best


def section_chunks(kb: dict, doc_id: str, section: str) -> tuple[list[dict], str | None]:
    """Find a section by number ('2.1.2', '6.1', 'п. 4') or title (fuzzy); return all its chunks (incl. subsections)."""
    chunks = [c for c in kb["chunks"] if c["doc_id"] == doc_id]
    if not chunks:
        return [], None
    sections = list(dict.fromkeys(" → ".join(c["section_path"]) for c in chunks))
    sec = section.strip()
    target = None
    m = re.match(r"^(\d+(?:\.\d+)*)\.?$", sec)
    if m:
        num = m.group(1)
        for s in sections:
            last = s.split(" → ")[-1] if s else ""
            if re.match(rf"^{re.escape(num)}\.?\s", last):
                target = s
                break
    if target is None and sections:
        best = process.extractOne(sec.lower(), {s: s.lower() for s in sections}, scorer=fuzz.WRatio)
        if best and best[1] >= 60:
            target = best[2]
    if target is None:
        return [], None
    out = [c for c in chunks if " → ".join(c["section_path"]).startswith(target)]
    return out, target


def known_names(kb: dict) -> list[str]:
    """Names a link slug may refer to, taken from the knowledge base itself: document titles, section
    names and short labels read from screenshots (menu items, window titles)."""
    if "names" in kb:
        return kb["names"]
    names: list[str] = [d["title"] for d in kb["docs"].values()]
    for d in kb["docs"].values():
        for sp in d["sections"]:
            names.append(re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", sp.split(" → ")[-1]))
    for c in kb["chunks"]:
        if c.get("chunk_type") != "image":
            continue
        for line in (c.get("text") or "").splitlines():
            if line.startswith("Надписи на изображении:"):
                names.extend(x.strip() for x in line.split(":", 1)[1].split("|"))
    out = [n for n in dict.fromkeys(names) if 3 <= len(n) <= 60 and len(n.split()) <= 6 and re.search(r"[А-Яа-яЁё]", n)]
    kb["names"] = out
    return out
