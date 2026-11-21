"""FR-ADM-05: «Документация обновлена» after a Git sync — what changed between two published generations, and an
optional push of a `docs.updated` event (same envelope as the digest push: {"events": [...]}) to DOCS_WEBHOOK_URL.

The receiving side (the bot's «Документация обновлена» + «Что изменилось», tg_bot delivery.notify_docs_updated) is
not part of the RAG service; until it accepts this event the URL stays empty and the diff is only in the sync report
(`GET /git/sources/{id}` → last_sync.changes)."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from .config import get_settings

log = logging.getLogger(__name__)


def _docs(manifest: dict | None) -> dict[str, dict]:
    return {d["doc_id"]: d for d in (manifest or {}).get("documents", [])}


def manifest_diff(before: dict | None, after: dict | None) -> dict:
    """Documents added / removed / changed (by content hash) and, for changed ones, sections added / removed."""
    b, a = _docs(before), _docs(after)
    out = {"added": [], "removed": [], "changed": []}
    for doc_id, d in a.items():
        old = b.get(doc_id)
        if old is None:
            out["added"].append({"doc_id": doc_id, "title": d.get("title")})
        elif (old.get("content_hash") or old.get("document_version")) != (d.get("content_hash") or d.get("document_version")):
            so, sn = [str(x) for x in old.get("outline") or []], [str(x) for x in d.get("outline") or []]
            out["changed"].append({"doc_id": doc_id, "title": d.get("title"),
                                   "sections_added": [x for x in sn if x not in so][:20],
                                   "sections_removed": [x for x in so if x not in sn][:20]})
    out["removed"] = [{"doc_id": k, "title": d.get("title")} for k, d in b.items() if k not in a]
    return out


def summary_text(changes: dict) -> str:
    """Short Russian text for «Что изменилось»."""
    lines = []
    for d in changes.get("added", []):
        lines.append(f"➕ Новый документ: {d['title']}")
    for d in changes.get("changed", []):
        extra = []
        if d["sections_added"]:
            extra.append("новые разделы: " + "; ".join(d["sections_added"][:5]))
        if d["sections_removed"]:
            extra.append("убраны разделы: " + "; ".join(d["sections_removed"][:5]))
        lines.append(f"✏️ Обновлён: {d['title']}" + (f" ({', '.join(extra)})" if extra else ""))
    for d in changes.get("removed", []):
        lines.append(f"➖ Удалён документ: {d['title']}")
    return "\n".join(lines)


def is_empty(changes: dict) -> bool:
    return not any(changes.get(k) for k in ("added", "removed", "changed"))


def push_docs_updated(project_id: str, generation: str | None, source: str, changes: dict, *, background: bool = True) -> bool:
    """POST a `docs.updated` event when DOCS_WEBHOOK_URL is set and something changed. Never raises."""
    s = get_settings()
    if not s.docs_webhook_url or is_empty(changes):
        return False
    ev = {"event_id": f"docs-{project_id}-{generation}"[:64], "type": "docs.updated", "project_id": project_id,
          "occurred_at": datetime.now(timezone.utc).isoformat(),
          "data": {"generation": generation, "source": source, "changes": changes, "summary": summary_text(changes)}}

    def send() -> None:
        import httpx

        try:
            headers = {"X-Service-Token": s.docs_webhook_token} if s.docs_webhook_token else {}
            httpx.post(s.docs_webhook_url, json={"events": [ev]}, headers=headers, timeout=20).raise_for_status()
        except Exception as e:  # noqa: BLE001  (a notification never breaks a sync)
            log.warning("docs.updated push failed: %s", e)

    if background:
        threading.Thread(target=send, daemon=True, name="docs-updated").start()
    else:
        send()
    return True
