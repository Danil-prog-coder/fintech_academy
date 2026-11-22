"""Daily digest of classified questions (instead of one `turn.classified` event per question).

`daily_digest(project_id, date, tz)` — one calendar day in `tz` (default QUESTION_DIGEST_TZ, Europe/Moscow) from
`rag_questions` (analytics/questions.py) and the LLM classifier's `rag_classes`:
counts by intent, on/off-topic, answered vs not, topic, question type (`qtype`) and subject (`subject` — names as in
`turn.classified` of mini_app/Docs/integration.md), documentation sections, complexity (simple / complex / cache);
top clusters of the day (count, distinct people, `trend` vs the previous 7 days — names as in `faq.snapshot`),
clusters created that day and unanswered clusters (documentation gaps) with example questions.

Optional push at the end of the day: DIGEST_WEBHOOK_URL (empty = off, the default). The digest is sent once per day
and project in the panel's event envelope (`POST {"events": [{event_id, type: "questions.daily_digest", project_id,
occurred_at, data}]}`, header X-Service-Token = DIGEST_WEBHOOK_TOKEN); `event_id` is fixed per project and date, so a
re-send is harmless.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from ..core import db
from ..core.config import get_settings
from .questions import _who

log = logging.getLogger(__name__)
Q, C = db.questions, db.question_clusters


def day_window(day: str | Date | None, tz: str | None) -> tuple[Date, float, float, ZoneInfo]:
    z = ZoneInfo(tz or get_settings().question_digest_tz)
    d = Date.fromisoformat(day) if isinstance(day, str) else day or datetime.now(z).date()
    start = datetime(d.year, d.month, d.day, tzinfo=z)
    end = start + timedelta(days=1)
    return d, start.timestamp(), end.timestamp(), z


_SUBJ_PREFIX = re.compile(r"^(?:бп|б\.п\.|бизнес[- ]процесс\w*|процесс\w*|раздел\w*|модул\w*|реестр\w*|документ\w*)\s+")


def subject_key(x: str) -> str:
    """«БП Командировка», «бизнес-процесс Командировка», «командировки» → «командиров»: lower case, no quotes,
    no generic prefix, word stems (first 8 letters)."""
    t = re.sub(r"[«»\"'`.,:;!?()]", " ", (x or "").lower()).replace("ё", "е").strip()
    while True:
        u = _SUBJ_PREFIX.sub("", t)
        if u == t or not u:
            break
        t = u
    return " ".join(w[:8] for w in t.split())


def merge_subjects(objects, top: int = 15) -> dict[str, int]:
    """Subjects of the LLM classifier merged by subject_key; shown under the most frequent spelling."""
    by: dict[str, Counter] = defaultdict(Counter)
    for o in objects:
        if o and str(o).strip():
            by[subject_key(str(o))][str(o).strip()] += 1
    merged = [(v.most_common(1)[0][0], sum(v.values())) for k, v in by.items() if k]
    merged.sort(key=lambda x: -x[1])
    return dict(merged[:top])


def _counts(rows: list[dict], key) -> dict:
    return dict(Counter(k for k in (key(r) for r in rows) if k is not None).most_common())


def daily_digest(project_id: str | None = None, day: str | Date | None = None, tz: str | None = None,
                 top: int = 10, examples: int = 3) -> dict:
    from .store import load_feedback

    s = get_settings()
    pid = project_id or s.default_project_id
    d, t0, t1, z = day_window(day, tz)
    rows = db.rows(sa.select(Q).where(Q.c.project_id == pid, Q.c.ts >= t0, Q.c.ts < t1).order_by(Q.c.ts))
    prev = db.rows(sa.select(Q.c.cluster_id, Q.c.ts).where(Q.c.project_id == pid, Q.c.ts >= t0 - 7 * 86400, Q.c.ts < t0,
                                                          Q.c.cluster_id.is_not(None)))
    meta = {r["cluster_id"]: r for r in db.rows(sa.select(C).where(C.c.project_id == pid))}
    ids = [r["request_id"] for r in rows]
    classes: dict[str, dict] = {}
    for i in range(0, len(ids), 500):
        for r in db.rows(sa.select(db.classes).where(db.classes.c.request_id.in_(ids[i:i + 500]))):
            classes[r["request_id"]] = r.get("data") or {}
    fb = load_feedback() if rows else {}
    on = [r for r in rows if r.get("on_topic")]

    def unanswered(r):
        return bool((r.get("data") or {}).get("unanswered"))

    from .insights import topic_of

    by_topic: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        t = by_topic[topic_of(r)]  # «Вне тематики» == off_topic
        t["count"] += 1
        t["answered"] += bool(r.get("answered"))
        t["unanswered"] += unanswered(r)
    prev_by = Counter(r["cluster_id"] for r in prev)
    by_cluster: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("cluster_id"):
            by_cluster[r["cluster_id"]].append(r)

    def cluster_item(cid: str, ms: list[dict]) -> dict:
        m = meta.get(cid) or {}
        base = prev_by.get(cid, 0) / 7
        un = [x for x in ms if unanswered(x)]
        return {"cluster_id": cid, "question": m.get("medoid") or ms[0]["text"], "label": m.get("label"),
                "topic": m.get("topic") or Counter(x.get("topic") for x in ms).most_common(1)[0][0],
                "count": len(ms), "people": len({_who(x) for x in ms}),
                "people_unit": "user" if any(x.get("user_ref") for x in ms) else "session",
                "answered": sum(1 for x in ms if x.get("answered")), "unanswered": len(un),
                "unanswered_people": len({_who(x) for x in un}),
                "likes": sum(1 for x in ms if fb.get(x["request_id"]) == "up"),
                "dislikes": sum(1 for x in ms if fb.get(x["request_id"]) == "down"),
                "trend": round(len(ms) / base, 2) if base else None,
                "new": bool(m.get("created_at") and t0 <= m["created_at"] < t1),
                "examples": list(dict.fromkeys(x["text"] for x in (un or ms)))[:examples],
                "request_ids": [x["request_id"] for x in ms][:50]}

    clusters = [cluster_item(cid, ms) for cid, ms in by_cluster.items()]
    clusters.sort(key=lambda c: (-c["people"], -c["count"]))
    gaps = sorted((c for c in clusters if c["unanswered"]), key=lambda c: (-c["unanswered_people"], -c["unanswered"], -c["count"]))
    new = [{"cluster_id": cid, "label": m.get("label"), "question": m.get("medoid"), "topic": m.get("topic"), "size": m.get("size")}
           for cid, m in meta.items() if m.get("created_at") and t0 <= m["created_at"] < t1]
    single_gaps = [{"request_id": r["request_id"], "question": r["text"], "topic": r.get("topic"), "outcome": r.get("outcome"),
                    "reason": (r.get("data") or {}).get("reason")} for r in rows if not r.get("cluster_id") and unanswered(r)]
    out = {
        "type": "questions.daily_digest", "project_id": pid, "date": d.isoformat(), "tz": z.key,
        "from": datetime.fromtimestamp(t0, timezone.utc).isoformat(), "to": datetime.fromtimestamp(t1, timezone.utc).isoformat(),
        "complete": time.time() >= t1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "questions": len(rows), "people": len({_who(r) for r in rows}),
        "intents": _counts(rows, lambda r: r.get("intent")),
        "blocked": _counts([r for r in rows if r.get("intent") == "blocked"], lambda r: (r.get("data") or {}).get("guard")),  # guard.py
        "on_topic": len(on), "off_topic": len(rows) - len(on),
        "answered": sum(1 for r in rows if r.get("answered")), "unanswered": sum(1 for r in rows if unanswered(r)),
        "answer_rate": round(sum(1 for r in on if r.get("answered")) / len(on), 3) if on else None,
        "outcomes": _counts(rows, lambda r: r.get("outcome")),
        "topics": sorted(({"topic": k, **v} for k, v in by_topic.items()), key=lambda x: -x["count"]),
        "qtypes": _counts(rows, lambda r: classes.get(r["request_id"], {}).get("type")),
        "subjects": merge_subjects(classes.get(r["request_id"], {}).get("object") for r in rows),
        "doc_sections": [{"section": k, "count": n} for k, n in Counter(r["doc_section"] for r in rows if r.get("doc_section")).most_common(15)],
        "complexity": _counts(on, lambda r: r.get("complexity") or "cache"),
        "clustered": sum(len(v) for v in by_cluster.values()),
        "top_clusters": clusters[:top], "new_clusters": new, "unanswered_clusters": gaps[:top],
        "unanswered_unclustered": single_gaps[:top],
        "likes": sum(1 for r in rows if fb.get(r["request_id"]) == "up"),
        "dislikes": sum(1 for r in rows if fb.get(r["request_id"]) == "down"),
        # tone / urgency from the trained classifier (analytics/qmodel.py), trends and spikes (analytics/insights.py)
        "sentiment": _counts(rows, lambda r: (r.get("data") or {}).get("sentiment")),
        "urgent": sum(1 for r in rows if (r.get("data") or {}).get("urgency") == "urgent"),
        "urgent_negative": [{"request_id": r["request_id"], "question": r["text"], "topic": r.get("topic"), "answered": r.get("answered")}
                            for r in rows if (r.get("data") or {}).get("urgency") == "urgent"
                            and (r.get("data") or {}).get("sentiment") == "negative"][:top],
        **_trend_part(pid, d, z.key, top),
    }
    if s.answer_clusters_enabled:  # optional field (ANSWER_CLUSTERS_ENABLED): absent otherwise, the contract is unchanged
        out["answer_clusters"] = _answer_part(pid, rows, top)
    return out


def _answer_part(pid: str, rows: list[dict], top: int) -> dict | None:
    """Answer clusters of the day (analytics/answers.py): FAQ / cache candidates, gaps, merge suggestions, consistency."""
    from .answers import build

    try:
        a = build(pid, days=1, rows=rows, top=top)
    except Exception as e:  # noqa: BLE001  (the digest never fails because of an optional block)
        log.warning("digest answer clusters: %s", e)
        return None
    slim = ("answer_cluster", "question", "answer", "count", "people", "sections", "answered_share", "source_consistency",
            "question_clusters", "outcomes", "examples")
    return {"questions": a["questions"], "groups": a["groups"],
            "faq_candidates": [{k: x.get(k) for k in slim} for x in a["faq_candidates"]],
            "gaps": [{k: x.get(k) for k in slim} for x in a["gaps"]],
            "merge_suggestions": a["merge_suggestions"], "answer_consistency": a["answer_consistency"]}


def _trend_part(pid: str, d: Date, tz: str, top: int) -> dict:
    """Spikes of the day and rising / falling topics and clusters over the 14 days ending that day."""
    from .insights import trends

    try:
        tr = trends(pid, days=14, tz=tz, end=d, limit=top)
    except Exception as e:  # noqa: BLE001  (the digest never fails on trends)
        log.warning("digest trends: %s", e)
        return {"spikes": [], "rising": [], "falling": []}
    return {"spikes": [x for x in tr["spikes"] if x["date"] == d.isoformat()], "rising": tr["rising"], "falling": tr["falling"]}


# ---------------------------------------------------------------------------------------- optional end-of-day push
def push(project_id: str | None = None, day: str | Date | None = None) -> dict:
    import httpx

    s = get_settings()
    dg = daily_digest(project_id, day)
    ev = {"event_id": f"digest-{dg['project_id']}-{dg['date']}"[:64], "type": "questions.daily_digest",
          "project_id": dg["project_id"], "occurred_at": dg["to"], "data": dg}
    headers = {"X-Service-Token": s.digest_webhook_token} if s.digest_webhook_token else {}
    r = httpx.post(s.digest_webhook_url, json={"events": [ev]}, headers=headers, timeout=20)
    r.raise_for_status()
    db.upsert(db.kv, "key", f"digest_sent:{dg['project_id']}"[:64], {"value": {"date": dg["date"], "at": time.time()}})
    return {"ok": True, "status": r.status_code, "date": dg["date"], "project_id": dg["project_id"]}


def _last_sent(pid: str) -> str | None:
    row = db.one(sa.select(db.kv.c.value).where(db.kv.c.key == f"digest_sent:{pid}"[:64]))
    return ((row or {}).get("value") or {}).get("date")


_worker: threading.Thread | None = None


def start_digest_worker() -> None:
    """Sends yesterday's digest once after midnight (+ QUESTION_DIGEST_DELAY_MIN) in QUESTION_DIGEST_TZ. Off without
    DIGEST_WEBHOOK_URL."""
    global _worker
    s = get_settings()
    if not s.digest_webhook_url or _worker:
        return

    def loop():
        while True:
            try:
                z = ZoneInfo(s.question_digest_tz)
                now = datetime.now(z)
                y = (now - timedelta(days=1)).date()
                pid = s.default_project_id
                if now.hour * 60 + now.minute >= s.question_digest_delay_min and _last_sent(pid) != y.isoformat():
                    log.info("daily digest sent: %s", push(pid, y))
            except Exception as e:  # noqa: BLE001  (a panel outage never affects answering; retried next round)
                log.warning("daily digest push: %s", e)
            time.sleep(300)

    _worker = threading.Thread(target=loop, daemon=True, name="questions-digest")
    _worker.start()
