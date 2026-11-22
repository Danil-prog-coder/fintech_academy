"""FR-GEN-02 (v1.8): clickable links from the sources block to the cited section of an uploaded PDF / DOCX / MD document.

Git documents already link to the file pinned to the commit (`source_url`, FR-GIT-02). For uploaded documents the RAG
service itself serves them:
- `GET /documents/{doc_id}/file#page=N` — the original PDF opened at the cited page (when the chunk has a page);
- `GET /documents/{doc_id}/view#sec-2.4.6` — the indexed document as a simple HTML page with an anchor per section
  (works for every format: DOCX, MD, PDF without pages, Confluence export).
A Telegram user has no API token, so links carry `sig` = HMAC(project_id, doc_id) — it opens only documents of this
project that the bot may cite anyway. The key is DOC_LINK_SECRET or, if empty, derived from the service token.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import re
from pathlib import Path
from urllib.parse import quote

from .config import Settings


def _key(s: Settings) -> bytes:
    k = s.doc_link_secret or s.service_api_token or s.admin_api_token
    return hmac.new(b"bars-doc-link-v1", k.encode(), hashlib.sha256).digest() if k else b""


def sign(s: Settings, project_id: str, doc_id: str) -> str:
    key = _key(s)
    return hmac.new(key, f"{project_id}\n{doc_id}".encode(), hashlib.sha256).hexdigest()[:24] if key else ""


def verify(s: Settings, project_id: str, doc_id: str, sig: str | None) -> bool:
    good = sign(s, project_id, doc_id)
    return bool(good and sig) and hmac.compare_digest(good, sig or "")


def anchor(section_number: str | None, section_path: list[str] | None) -> str:
    if section_number:
        return "sec-" + section_number
    path = " / ".join(section_path or [])
    return "sec-" + hashlib.sha1(path.encode()).hexdigest()[:10] if path else ""


def original_file(s: Settings, doc: dict | None, project_id: str | None = None) -> Path | None:
    """The uploaded original in KB_DIR (not for Git documents — they link to the repository)."""
    if not doc or doc.get("git") or not doc.get("file"):
        return None
    from .project_paths import upload_dir

    if doc.get("original_file"):
        original = Path(doc["original_file"]).resolve()
        root = (Path(s.state_dir) / "originals").resolve()
        if original.is_relative_to(root) and original.is_file():
            return original
        return None
    p = upload_dir(s, project_id or s.default_project_id) / Path(doc["file"]).name
    return p if p.is_file() else None


def source_link(s: Settings, project_id: str, src: dict, doc: dict | None) -> str | None:
    """URL for one cited source (None: links off, no public URL, or nothing to link to)."""
    if not s.doc_links or not s.public_base_url or not src.get("doc_id") or src.get("kind") == "tool":
        return None
    doc_id = src["doc_id"]
    q = f"?project_id={quote(project_id)}"
    sig = sign(s, project_id, doc_id)
    if sig:
        q += f"&sig={sig}"
    elif not s.auth_disabled:
        return None  # no key to sign with: the link would answer 401/503
    base = s.public_base_url.rstrip("/") + f"/documents/{quote(doc_id)}"
    f = original_file(s, doc, project_id)
    if f is not None and f.suffix.lower() == ".pdf" and src.get("page"):
        return f"{base}/file{q}#page={int(src['page'])}"
    a = anchor(src.get("section_number"), src.get("section_path"))
    return f"{base}/view{q}" + (f"#{a}" if a else "")


_CSS = ("body{font:15px/1.5 system-ui,sans-serif;max-width:900px;margin:2em auto;padding:0 1em;color:#222}"
        "h1{font-size:1.4em}h2{font-size:1.1em;margin-top:1.6em;border-bottom:1px solid #ddd}"
        ":target{background:#fff6c8}.img{color:#555;border-left:3px solid #9ab;padding:.3em .8em;margin:.6em 0}"
        "pre{white-space:pre-wrap;font:inherit;margin:.4em 0}img{max-width:100%;border:1px solid #ccc}")


def render_view(doc: dict, chunks: list[dict], img_url) -> str:
    """The indexed document as HTML: one heading per section (id = anchor), chunk texts in order, screenshots inline.
    `img_url(image_id)` gives a link for an image of this document."""
    out = [f"<!doctype html><html lang=ru><meta charset=utf-8><title>{html.escape(doc.get('title') or '')}</title>"
           f"<style>{_CSS}</style><h1>{html.escape(doc.get('title') or '')}</h1>"]
    seen_sec: set[str] = set()
    seen_text: set[str] = set()
    for c in chunks:
        a = anchor(c.get("section_number"), c.get("section_path"))
        if a and a not in seen_sec:
            seen_sec.add(a)
            out.append(f"<h2 id=\"{html.escape(a)}\">{html.escape((c.get('section_path') or [''])[-1])}</h2>")
        text = (c.get("text") or "").strip()
        if not text or text in seen_text:
            continue
        seen_text.add(text)
        if c.get("chunk_type") == "image":
            imgs = "".join(f"<img src=\"{html.escape(img_url(i))}\" alt=\"\" loading=lazy>" for i in c.get("image_ids") or [])
            first = re.split(r"\n", text, maxsplit=1)[0]
            out.append(f"<div class=img>{imgs}<pre>{html.escape(first)}</pre></div>")
        else:
            out.append(f"<pre>{html.escape(text)}</pre>")
    return "".join(out) + "</html>"
