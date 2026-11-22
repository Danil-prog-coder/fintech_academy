"""Analytics for the admin dashboard (FR-AN-02, FR-AN-03 data, FR-AN-05, FR-FAQ-02 «места документации»).

All numbers come from the query log (FR-AN-01) joined with 👍/👎 feedback and the async classification (FR-AN-04).
Duty-ticket metrics (time to take / close, user rating) need the Jira/Postgres escalation backend, which is not
part of this RAG service — they are returned as null with an explanation.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

from ..core.config import get_settings
from ..index import store
from .classify import get_classifier
from .store import feedback_history, is_success, load_escalation_marks, load_feedback, load_turns, outcome


def _tokens(r: dict) -> int:
    u = r.get("usage") or {}
    return int(u.get("prompt_tokens", 0) or 0) + int(u.get("completion_tokens", 0) or 0)


def _cost(r: dict) -> float:
    s = get_settings()
    u = r.get("usage") or {}
    if u.get("cost_usd") is not None:
        return float(u["cost_usd"])  # real cost reported by OpenRouter
    return (u.get("prompt_tokens", 0) or 0) / 1e6 * s.llm_price_in_per_mtok + (u.get("completion_tokens", 0) or 0) / 1e6 * s.llm_price_out_per_mtok


def _section(sp: str, depth: int = 3) -> str:
    return " → ".join(sp.split(" → ")[:depth])


def _routing(recs: list[dict]) -> dict:
    """Model routing: share of turns finished on the fast tier, latency and cost per tier."""
    tiers = [r for r in recs if r.get("tier")]
    out: dict = {"turns": len(tiers), "fast_share": round(sum(r["tier"] == "fast" for r in tiers) / len(tiers), 3) if tiers else None}
    for t in ("fast", "heavy"):
        rs = [r for r in tiers if r["tier"] == t]
        lat = sorted(r.get("latency_ms") or 0 for r in rs)
        out[t] = {"turns": len(rs), "avg_latency_ms": int(sum(lat) / len(lat)) if lat else None,
                  "p90_latency_ms": lat[int(0.9 * (len(lat) - 1))] if lat else None,
                  "cost_usd": round(sum(_cost(r) for r in rs), 5),
                  "answer_rate": round(sum(r.get("action") == "answer" for r in rs) / len(rs), 3) if rs else None}
    return out


def summary(days: int = 7, project_id: str | None = None) -> dict:
    """FR-AN-02 base metrics. Keys of the earlier /analytics/summary are kept for compatibility."""
    recs = load_turns(days, project_id)
    fb = load_feedback()
    classes = get_classifier().load()
    now = time.time()
    n = len(recs)
    acts = Counter(r.get("action") for r in recs)
    lat = sorted(r.get("latency_ms") or 0 for r in recs)
    secs = Counter(_section(sp, 2) for r in recs for sp in set(r.get("sources") or []) if sp)
    ratings = Counter(fb.get(r.get("request_id")) for r in recs)
    marks = load_escalation_marks()
    ft = sorted(r["first_token_ms"] for r in recs if r.get("first_token_ms") is not None and outcome(r) != "cache_answer")
    cache = [r for r in recs if outcome(r) == "cache_answer"]
    agent = [r for r in recs if outcome(r) != "cache_answer" and r.get("action") == "answer" and _tokens(r)]
    avg_tokens = (sum(_tokens(r) for r in agent) / len(agent)) if agent else 0.0
    avg_cost = (sum(_cost(r) for r in agent) / len(agent)) if agent else 0.0
    topics = Counter((classes.get(r.get("request_id")) or {}).get("topic") or "не классифицировано" for r in recs)
    return {
        "days": days, "requests": n, "actions": dict(acts),
        "requests_day": sum(1 for r in recs if now - r.get("ts", 0) <= 86400),
        "requests_week": sum(1 for r in recs if now - r.get("ts", 0) <= 7 * 86400),
        "auto_answer_rate": round(acts.get("answer", 0) / n, 3) if n else None,
        # FR-AN-02: successful auto-answer = answer without escalation and without 👎
        "success_rate": round(sum(1 for r in recs if is_success(r, fb.get(r.get("request_id")))) / n, 3) if n else None,
        "escalation_rate": round((acts.get("escalate", 0) + acts.get("offer_operator", 0)) / n, 3) if n else None,
        "escalations": {"escalate": acts.get("escalate", 0), "offer_operator": acts.get("offer_operator", 0),
                        "reasons": dict(Counter(r.get("reason") for r in recs if r.get("action") in ("escalate", "offer_operator")))},
        "cache_hits": len(cache),
        "cache": {
            "share": round(len(cache) / n, 3) if n else None,
            "by_level": dict(Counter(r.get("cache_level") or "exact" for r in cache)),
            "saved_tokens_est": int(avg_tokens * len(cache)), "saved_cost_usd_est": round(avg_cost * len(cache), 4),
            "dislikes": sum(1 for r in cache if fb.get(r.get("request_id")) == "down"),
        },
        "feedback": {"up": ratings.get("up", 0), "down": ratings.get("down", 0)},
        # FR-ESC-08: escalations the duty operator marked as unnecessary
        "escalations_marked_unneeded": sum(1 for r in recs if marks.get(r.get("request_id"))),
        "latency_ms": {"avg": int(sum(lat) / n) if n else None, "p90": lat[int(0.9 * (n - 1))] if n else None},
        # NFR-01: time to the first shown text (answers generated by the agent, not served from a cache)
        "first_token_ms": {"avg": int(sum(ft) / len(ft)) if ft else None, "p90": ft[int(0.9 * (len(ft) - 1))] if ft else None},
        "confidence_levels": dict(Counter(r.get("confidence_level") for r in recs)),
        "top_topics": topics.most_common(10),
        "top_doc_sections": secs.most_common(10),
        "tokens": sum(_tokens(r) for r in recs),
        "cost_usd_est": round(sum(_cost(r) for r in recs), 4),
        "routing": _routing(recs),
        "duty": {"time_to_take_s": None, "time_to_close_s": None, "user_rating": None,
                 "note": "нужны данные Jira/Postgres эскалаций (FR-ESC-03) — вне RAG-сервиса"},
    }


def timeseries(days: int = 7, bucket: str = "day", project_id: str | None = None) -> dict:
    """FR-AN-03: per-day (or per-hour) series for the dashboard charts."""
    recs = load_turns(days, project_id)
    fb = load_feedback()
    fmt = "%Y-%m-%d" if bucket == "day" else "%Y-%m-%d %H:00"
    rows: dict[str, dict] = defaultdict(lambda: {"requests": 0, "answers": 0, "success": 0, "escalations": 0, "cache": 0,
                                                 "down": 0, "latency_sum": 0})
    for r in recs:
        k = datetime.fromtimestamp(r.get("ts", 0), tz=timezone.utc).strftime(fmt)
        row = rows[k]
        rating = fb.get(r.get("request_id"))
        row["requests"] += 1
        row["answers"] += r.get("action") == "answer"
        row["success"] += is_success(r, rating)
        row["escalations"] += r.get("action") in ("escalate", "offer_operator")
        row["cache"] += outcome(r) == "cache_answer"
        row["down"] += rating == "down"
        row["latency_sum"] += r.get("latency_ms") or 0
    series = []
    for k in sorted(rows):
        row = rows[k]
        series.append({"bucket": k, **{x: row[x] for x in ("requests", "answers", "success", "escalations", "cache", "down")},
                       "avg_latency_ms": int(row["latency_sum"] / row["requests"]) if row["requests"] else None})
    return {"days": days, "bucket": bucket, "tz": "UTC", "series": series}


def distribution(days: int = 30, project_id: str | None = None) -> dict:
    """FR-AN-04 on the dashboard: topics × question types × outcomes."""
    recs = load_turns(days, project_id)
    fb = load_feedback()
    classes = get_classifier().load()
    topic, qtype, objs = Counter(), Counter(), Counter()
    by_topic: dict[str, Counter] = defaultdict(Counter)
    unclassified = 0
    for r in recs:
        c = classes.get(r.get("request_id"))
        if not c:
            unclassified += 1
            continue
        topic[c["topic"]] += 1
        qtype[c["type"]] += 1
        if c.get("object"):
            objs[c["object"]] += 1
        by_topic[c["topic"]][outcome(r)] += 1
        if fb.get(r.get("request_id")):
            by_topic[c["topic"]][fb[r["request_id"]]] += 1
    return {"days": days, "topics": topic.most_common(), "types": qtype.most_common(), "objects": objs.most_common(15),
            "outcomes_by_topic": {k: dict(v) for k, v in by_topic.items()}, "unclassified": unclassified,
            "taxonomy": get_classifier().taxonomy()}


def requests(days: int = 7, limit: int = 50, action: str | None = None, project_id: str | None = None) -> list[dict]:
    """FR-AN-03: table of the latest requests (→ GET /analytics/requests/{id} for the dialog and agent trace)."""
    fb = load_feedback()
    classes = get_classifier().load()
    out = []
    for r in reversed(load_turns(days, project_id)):
        if action and r.get("action") != action:
            continue
        c = classes.get(r.get("request_id")) or {}
        out.append({"ts": r.get("ts"), "request_id": r.get("request_id"), "session": r.get("session"), "text": r.get("text"),
                    "action": r.get("action"), "outcome": outcome(r), "reason": r.get("reason"), "confidence": r.get("confidence"),
                    "latency_ms": r.get("latency_ms"), "topic": c.get("topic"), "type": c.get("type"),
                    "feedback": fb.get(r.get("request_id")), "trace_steps": len(r.get("trace") or [])})
        if len(out) >= limit:
            break
    return out


def request_detail(request_id: str) -> dict | None:
    from .store import find_turn

    r = find_turn(request_id)
    if not r:
        return None
    dialog = [x for x in load_turns(60) if x.get("session") == r.get("session")]
    return {"turn": r, "classification": get_classifier().load().get(request_id), "feedback": load_feedback().get(request_id),
            "feedback_history": feedback_history(request_id),
            "dialog": [{"ts": x.get("ts"), "request_id": x.get("request_id"), "text": x.get("text"), "action": x.get("action")} for x in dialog]}


def doc_sections(days: int = 30, project_id: str | None = None) -> dict:
    """FR-FAQ-02 «места документации»: which sections answers rely on (with which questions), which are never used,
    and which collect 👎 / escalations (candidates for rewriting)."""
    pid = project_id or get_settings().default_project_id
    recs = load_turns(days, pid)
    fb = load_feedback()
    used: dict[str, dict] = {}
    for r in recs:
        bad = fb.get(r.get("request_id")) == "down" or r.get("action") in ("escalate", "offer_operator")
        for sp in set(r.get("sources") or []):
            if not sp:
                continue
            k = _section(sp)
            u = used.setdefault(k, {"section": k, "answers": 0, "bad": 0, "questions": Counter()})
            u["answers"] += 1
            u["bad"] += bad
            u["questions"][(r.get("text") or "")[:120]] += 1
    rows = sorted(({**u, "questions": u["questions"].most_common(3)} for u in used.values()), key=lambda x: -x["answers"])
    outline = []
    for d in store.active_manifest(pid).get("documents", []):
        for sp in d.get("outline") or []:
            outline.append(_section(f"{d['title']} → {sp}"))
    outline = list(dict.fromkeys(outline))
    used_keys = set(used)
    unused = [o for o in outline if not any(k == o or k.startswith(o + " → ") or o.startswith(k + " → ") for k in used_keys)]
    return {"days": days, "used": rows, "unused": unused[:200],
            "rewrite_candidates": [r["section"] for r in rows if r["answers"] >= 2 and r["bad"] / r["answers"] >= 0.3]}


def gaps(days: int = 30, project_id: str | None = None, threshold: float | None = None) -> dict:
    """FR-AN-05: clusters of questions without a good answer (offer_operator / escalation for lack of docs,
    low confidence, 👎) — «чего не хватает в документации»."""
    from ..faq import get_faq

    pid = project_id or get_settings().default_project_id
    fb = load_feedback()
    bad = []
    for r in load_turns(days, pid):
        rating = fb.get(r.get("request_id"))
        why = None
        if r.get("action") == "offer_operator":
            why = r.get("reason") or "offer_operator"
        elif r.get("action") == "escalate" and r.get("reason") not in ("user_request", None):
            why = f"escalate:{r.get('reason')}"
        elif r.get("action") == "answer" and (r.get("confidence_level") == "low" or r.get("reason") == "partial_answer"):
            why = r.get("reason") or "low_confidence"
        if rating == "down":
            why = "dislike" if not why else f"{why}+dislike"
        if why and (r.get("text") or "").strip():
            bad.append({"text": r["text"], "ts": r.get("ts", 0), "rec": r, "why": why})
    if not bad:
        return {"days": days, "questions": 0, "gaps": []}
    clusters = get_faq().cluster(pid, bad, threshold=threshold)
    out = []
    for c in clusters:
        whys = Counter(m["why"] for m in c["members"])
        tried = Counter(sp for m in c["members"] for sp in set(m["rec"].get("sources") or []) if sp)
        out.append({"question": c["canonical"], "count": c["count"], "examples": list(dict.fromkeys(c["texts"]))[:5],
                    "why": dict(whys), "entities": c["entities"], "nearest_sections": [_section(k) for k, _ in tried.most_common(3)],
                    "last_seen": max(m["ts"] for m in c["members"])})
    return {"days": days, "questions": len(bad), "gaps": out}


