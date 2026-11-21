"""Query-log access for analytics and the FAQ module (FR-AN-01..05, FR-BOT-04 feedback).

Turns are rows of `rag_turns` written by QueryLogger; feedback (👍/👎, «эскалация была не нужна») is the
append-only table `rag_feedback` joined to turns by `request_id`. Turns produced by the FAQ answer builder
(session «faq-build-…») are marked `internal` and excluded from every statistic.
"""

from __future__ import annotations

import time

import sqlalchemy as sa

from .. import db
from .query_logger import pseudonymize

T, F = db.turns, db.feedback


def load_turns(days: float = 7, project_id: str | None = None, include_internal: bool = False) -> list[dict]:
    """Turns of the last `days` days, oldest first. Old records get `standalone` inferred (first turn of the session)."""
    since = time.time() - days * 86400
    cond = [T.c.ts >= since]
    if project_id:
        cond.append(T.c.project_id == project_id)
    if not include_internal:
        cond.append(sa.or_(T.c.internal.is_(None), T.c.internal.is_(False)))
    out = [r["record"] for r in db.rows(sa.select(T.c.record).where(*cond).order_by(T.c.ts)) if r["record"]]
    if any(r.get("standalone") is None for r in out):
        seen = {r["session"] for r in db.rows(sa.select(T.c.session).where(T.c.ts < since).distinct())}
        for r in out:
            sess = r.get("session")
            if r.get("standalone") is None:
                r["standalone"] = sess not in seen
            seen.add(sess)
    return out


def write_turns(recs: list[dict]) -> int:
    """Insert ready query-log records (import of an older JSON-lines log, tests). Returns the number written."""
    n = 0
    for r in recs:
        if not r.get("request_id"):
            continue
        db.upsert(T, "request_id", r["request_id"], {
            "ts": r.get("ts") or time.time(), "project_id": r.get("project_id"), "session": r.get("session"),
            "action": r.get("action"), "internal": bool(r.get("internal")), "record": r})
        n += 1
    return n


def find_turn(request_id: str, days: float = 60) -> dict | None:
    row = db.one(sa.select(T.c.record).where(T.c.request_id == request_id, T.c.ts >= time.time() - days * 86400))
    return row["record"] if row else None


# ------------------------------------------------------------------ feedback (FR-BOT-04 → FR-AN-02, FR-FAQ-05)
def record_feedback(request_id: str, rating: str, session_id: str | None = None, comment: str | None = None) -> dict:
    rec = {"ts": time.time(), "request_id": request_id, "kind": "rating", "rating": rating,
           "session": pseudonymize(session_id) if session_id else None, "comment": (comment or "")[:500] or None}
    db.execute(sa.insert(F).values(**rec))
    return rec


def record_escalation_unneeded(request_id: str, unneeded: bool = True, comment: str | None = None) -> dict:
    """FR-ESC-08: the operator's «Эскалация была не нужна» mark on an escalation card."""
    rec = {"ts": time.time(), "request_id": request_id, "kind": "escalation_unneeded", "rating": "yes" if unneeded else "no",
           "session": None, "comment": (comment or "")[:500] or None}
    db.execute(sa.insert(F).values(**rec))
    return rec


def load_feedback() -> dict[str, str]:
    """request_id → last rating ('up' | 'down')."""
    return {r["request_id"]: r["rating"]
            for r in db.rows(sa.select(F.c.request_id, F.c.rating).where(F.c.kind == "rating").order_by(F.c.ts, F.c.id))}


def load_escalation_marks() -> dict[str, bool]:
    """request_id → last «эскалация была не нужна» mark."""
    return {r["request_id"]: r["rating"] == "yes"
            for r in db.rows(sa.select(F.c.request_id, F.c.rating).where(F.c.kind == "escalation_unneeded").order_by(F.c.ts, F.c.id))}


def feedback_history(request_id: str) -> list[dict]:
    return db.rows(sa.select(F.c.ts, F.c.kind, F.c.rating, F.c.comment).where(F.c.request_id == request_id).order_by(F.c.ts, F.c.id))


def search_queries(rec: dict) -> list[str]:
    """Search queries the agent formulated in this turn (from the trace)."""
    if rec.get("search_queries"):
        return list(rec["search_queries"])
    out = []
    for t in rec.get("trace") or []:
        if t.get("step") == "tool" and t.get("tool") == "search_docs":
            q = (t.get("args") or {}).get("query")
            if q:
                out.append(q)
    return out


def outcome(rec: dict, rating: str | None = None) -> str:
    """FR-AN-04 «исход»: answer / cache_answer / clarify / escalate / offer_operator (+ 👍/👎 separately)."""
    if rec.get("cache_hit") or rec.get("reason") == "cache_hit":
        return "cache_answer"
    return rec.get("action") or "unknown"


def is_success(rec: dict, rating: str | None) -> bool:
    """FR-AN-02: successful auto-answer = answer without escalation and without 👎."""
    return rec.get("action") == "answer" and rating != "down"
