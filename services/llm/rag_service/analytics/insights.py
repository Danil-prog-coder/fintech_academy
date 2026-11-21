"""Question analytics on top of rag_questions / rag_question_clusters (analytics/questions.py), numpy only:

* trends and spikes — daily counts per topic and per cluster in the digest time zone; a **spike** is a day with
  ≥ QUESTION_SPIKE_MIN questions and a Poisson z-score ≥ QUESTION_SPIKE_Z over the mean of the previous 7 days (and at
  least twice that mean); a **trend** compares the last 7 days with the 7 before (z = (a − b) / √(a + b + 1),
  rising at z ≥ 2, falling at z ≤ −2);
* hierarchy — topic → clusters (sub-topics) → example questions, with counts, people, answer rate, trend, tone;
* 2-D map — PCA of the question embeddings (the vectors retrieval already cached) for a scatter plot in the panel.
"""
from __future__ import annotations

import math
import time
from collections import Counter
from datetime import date as Date
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import sqlalchemy as sa

from .. import db
from ..config import get_settings

C = db.question_clusters
OFF_TOPIC = "Вне тематики"
NO_TOPIC = "Без темы"


def topic_of(r: dict) -> str:
    """One topic per question for every report: off-topic questions are «Вне тематики» (so its count equals off_topic),
    an on-topic question never is (legacy rows with that label are shown as «Без темы»)."""
    if not r.get("on_topic"):
        return OFF_TOPIC
    t = r.get("topic")
    return NO_TOPIC if not t or t == OFF_TOPIC else t


# ------------------------------------------------------------------------------------------------ pure functions
def spikes(series: list[int], z_thr: float | None = None, min_count: int | None = None, base_days: int = 7,
           start: int = 0) -> list[dict]:
    """Days (indices) where the count jumps over the previous `base_days` days; days before `start` (no data was
    collected yet) are not history."""
    s = get_settings()
    z_thr = s.question_spike_z if z_thr is None else z_thr
    min_count = s.question_spike_min if min_count is None else min_count
    out = []
    for d, x in enumerate(series):
        prev = series[max(start, d - base_days):d]
        if len(prev) < 5:  # not enough history
            continue
        mu = sum(prev) / len(prev)
        z = (x - mu) / math.sqrt(mu + 1)
        if x >= min_count and z >= z_thr and x >= 2 * mu:
            out.append({"day": d, "count": x, "baseline": round(mu, 2), "z": round(z, 2)})
    return out


def trend(series: list[int], window: int = 7, start: int = 0) -> dict:
    """Last `window` days vs the `window` before. The slope is fitted on the same 2 × window days (and only on days
    with history), so it does not depend on how long the requested series is (topic tree 30 days vs trends 14)."""
    a, b = sum(series[-window:]), sum(series[-2 * window:-window])
    history = len(series) - start
    seg = series[max(start, len(series) - 2 * window):]
    if len(seg) >= 2:
        slope = float(np.polyfit(np.arange(len(seg), dtype=float), np.asarray(seg, dtype=float), 1)[0])
    else:
        slope = 0.0
    if history < window + 3:  # the log is too young to compare two weeks: no z / change that could mislead
        return {"last": a, "previous": b, "change": None, "z": None, "history_days": history,
                "slope_per_day": round(slope, 3), "status": "insufficient_history"}
    z = (a - b) / math.sqrt(a + b + 1)
    status = "new" if b == 0 and a >= 3 else "rising" if z >= 2 else "falling" if z <= -2 else "stable"
    return {"last": a, "previous": b, "change": round((a - b) / b, 3) if b else None, "z": round(z, 2), "history_days": history,
            "slope_per_day": round(slope, 3), "status": status}


def pca2(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """2-D PCA: (coords, mean, components)."""
    mu = X.mean(0)
    _, _, vt = np.linalg.svd(X - mu, full_matrices=False)
    comp = vt[:2]
    return (X - mu) @ comp.T, mu, comp


# ------------------------------------------------------------------------------------------------ data access
def _window(days: int, tz: str | None, end: str | Date | None) -> tuple[list[Date], ZoneInfo, float, float]:
    z = ZoneInfo(tz or get_settings().question_digest_tz)
    last = Date.fromisoformat(end) if isinstance(end, str) else end or datetime.now(z).date()
    first = last - timedelta(days=days - 1)
    dates = [first + timedelta(days=i) for i in range(days)]
    t0 = datetime(first.year, first.month, first.day, tzinfo=z).timestamp()
    t1 = datetime(last.year, last.month, last.day, tzinfo=z).timestamp() + 86400
    return dates, z, t0, t1


def _rows(pid: str, t0: float, t1: float) -> list[dict]:
    Q = db.questions
    return db.rows(sa.select(Q).where(Q.c.project_id == pid, Q.c.ts >= t0, Q.c.ts < t1).order_by(Q.c.ts))


def _series(rows: list[dict], key, dates: list[Date], z: ZoneInfo) -> dict[str, list[int]]:
    idx = {d: i for i, d in enumerate(dates)}
    out: dict[str, list[int]] = {}
    for r in rows:
        k = key(r)
        if not k:
            continue
        i = idx.get(datetime.fromtimestamp(r["ts"], z).date())
        if i is not None:
            out.setdefault(k, [0] * len(dates))[i] += 1
    return out


def first_ts(pid: str) -> float | None:
    Q = db.questions
    row = db.one(sa.select(sa.func.min(Q.c.ts).label("ts")).where(Q.c.project_id == pid))
    return (row or {}).get("ts")


def trends(project_id: str | None = None, days: int = 14, tz: str | None = None, end: str | Date | None = None,
           limit: int = 30) -> dict:
    """Daily series, trend and spikes per topic and per cluster (GET /analytics/trends)."""
    pid = project_id or get_settings().default_project_id
    dates, z, t0, t1 = _window(days, tz, end)
    rows = _rows(pid, t0, t1)
    meta = {r["cluster_id"]: r for r in db.rows(sa.select(C).where(C.c.project_id == pid))}
    first = first_ts(pid)  # history starts with the project's first question, not with the window
    start = next((i for i, d in enumerate(dates) if first is not None and datetime.fromtimestamp(first, z).date() <= d), len(dates))

    def items(series: dict[str, list[int]], extra) -> list[dict]:
        out = []
        for k, ser in series.items():
            sp = spikes(ser, start=start)
            out.append({**extra(k), "total": sum(ser), "series": ser, "trend": trend(ser, start=start),
                        "spikes": [{**x, "date": dates[x["day"]].isoformat()} for x in sp]})
        out.sort(key=lambda x: (-x["total"]))
        return out

    on = [r for r in rows if r.get("on_topic")]
    topics = items(_series(on, topic_of, dates, z), lambda k: {"topic": k})
    clusters = items(_series(on, lambda r: r.get("cluster_id"), dates, z),
                     lambda k: {"cluster_id": k, "label": (meta.get(k) or {}).get("label"), "topic": (meta.get(k) or {}).get("topic")})
    flat = [{"level": "topic", "topic": t["topic"], **s} for t in topics for s in t["spikes"]]
    flat += [{"level": "cluster", "cluster_id": c["cluster_id"], "label": c["label"], "topic": c["topic"], **s}
             for c in clusters for s in c["spikes"]]
    flat.sort(key=lambda x: (x["date"], -x["z"]), reverse=True)
    total = [0] * len(dates)
    for ser in _series(rows, lambda r: "all", dates, z).values():
        total = ser
    return {"project_id": pid, "tz": z.key, "days": [d.isoformat() for d in dates], "questions": len(rows),
            "history_from": dates[start].isoformat() if start < len(dates) else None,
            "total": {"series": total, "trend": trend(total, start=start),
                      "spikes": [{**x, "date": dates[x["day"]].isoformat()} for x in spikes(total, start=start)]},
            "rising": [{k: x.get(k) for k in ("topic", "cluster_id", "label") if k in x} | {"trend": x["trend"]}
                       for x in topics + clusters if x["trend"]["status"] in ("rising", "new")][:limit],
            "falling": [{k: x.get(k) for k in ("topic", "cluster_id", "label") if k in x} | {"trend": x["trend"]}
                        for x in topics + clusters if x["trend"]["status"] == "falling"][:limit],
            "spikes": flat[:limit], "topics": topics[:limit], "clusters": clusters[:limit]}


def topic_tree(project_id: str | None = None, days: float = 30, clusters_per_topic: int = 20, examples: int = 3) -> dict:
    """Hierarchy topic → clusters → example questions (GET /analytics/topics/tree)."""
    from .questions import _who, clusterable

    s = get_settings()
    pid = project_id or s.default_project_id
    n_days = min(366, max(1, math.ceil(days)))
    dates, z, t0, t1 = _window(n_days, None, None)  # the same calendar days as /analytics/trends?days=n
    rows = _rows(pid, t0, t1)
    meta = {r["cluster_id"]: r for r in db.rows(sa.select(C).where(C.c.project_id == pid))}
    tr = trends(pid, days=n_days, limit=10**6)
    t_trend = {t["topic"]: t["trend"] for t in tr["topics"]}
    c_trend = {c["cluster_id"]: c["trend"] for c in tr["clusters"]}
    by_topic: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("on_topic"):
            by_topic.setdefault(topic_of(r), []).append(r)
    members: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("on_topic") and r.get("cluster_id"):
            members.setdefault(r["cluster_id"], []).append(r)
    home = {cid: Counter(topic_of(x) for x in cm).most_common(1)[0][0] for cid, cm in members.items()}

    def stats(ms: list[dict]) -> dict:
        d = [x.get("data") or {} for x in ms]
        return {"count": len(ms), "people": len({_who(x) for x in ms}),
                "answered": sum(1 for x in ms if x.get("answered")),
                "unanswered": sum(1 for x in d if x.get("unanswered")),
                "answer_rate": round(sum(1 for x in ms if x.get("answered")) / len(ms), 3) if ms else None,
                "intents": dict(Counter(x.get("intent") for x in ms)),
                "sentiment": dict(Counter(x.get("sentiment") for x in d if x.get("sentiment"))),
                "urgent": sum(1 for x in d if x.get("urgency") == "urgent")}

    out = []
    for topic, ms in by_topic.items():
        subs = []
        for cid in [c for c, h in home.items() if h == topic]:
            cm = members[cid]
            m = meta.get(cid) or {}
            subs.append({"cluster_id": cid, "label": m.get("label") or m.get("medoid"), "medoid": m.get("medoid"), **stats(cm),
                         "topic_share": round(sum(1 for x in cm if topic_of(x) == topic) / len(cm), 3),
                         "needs_docs": len(cm) >= 2 and sum(1 for x in cm if (x.get("data") or {}).get("unanswered")) / len(cm) >= s.question_gap_share,
                         "trend": c_trend.get(cid), "examples": list(dict.fromkeys(x["text"] for x in reversed(cm)))[:examples]})
        subs.sort(key=lambda c: (-c["people"], -c["count"]))
        single = [x for x in ms if not x.get("cluster_id") and clusterable(x)]
        out.append({"topic": topic, **stats(ms), "trend": t_trend.get(topic), "clusters": subs[:clusters_per_topic],
                    "clusters_total": len(subs), "unclustered": len(single),
                    "unclustered_examples": list(dict.fromkeys(x["text"] for x in reversed(single)))[:examples]})
    out.sort(key=lambda t: (-t["people"], -t["count"]))
    off = [r for r in rows if not r.get("on_topic")]
    return {"project_id": pid, "days": n_days, "from": dates[0].isoformat(), "to": dates[-1].isoformat(), "tz": z.key,
            "questions": len(rows), "on_topic": len(rows) - len(off),
            "off_topic": {"count": len(off), "intents": dict(Counter(r.get("intent") for r in off))}, "topics": out}


def cluster_map(project_id: str | None = None, days: float = 30, limit: int = 600) -> dict:
    """2-D PCA of question embeddings for a scatter plot: points (questions) and cluster centres."""
    from .embedder import embed
    from .questions import _unit, cluster_model, clusterable

    pid = project_id or get_settings().default_project_id
    t1 = time.time()
    rows = [r for r in _rows(pid, t1 - days * 86400, t1 + 1) if clusterable(r)][-limit:]
    meta = {r["cluster_id"]: r for r in db.rows(sa.select(C).where(C.c.project_id == pid, C.c.active.is_(True)))}
    if len(rows) < 3:
        return {"project_id": pid, "days": days, "points": [], "clusters": [], "explained": None}
    vecs, model = embed([r["text"] for r in rows])
    X = np.stack(vecs)
    xy, mu, comp = pca2(X)
    scale = float(np.abs(xy).max()) or 1.0
    var = np.var(X - mu, axis=0).sum()
    explained = [round(float(np.var(xy[:, i]) / var), 3) for i in range(2)] if var else None
    pts = [{"request_id": r["request_id"], "text": r["text"][:200], "x": round(float(p[0] / scale), 4), "y": round(float(p[1] / scale), 4),
            "cluster_id": r.get("cluster_id"), "topic": r.get("topic")} for r, p in zip(rows, xy)]
    sizes = Counter(r.get("cluster_id") for r in rows if r.get("cluster_id"))
    cl = []
    for cid, m in meta.items():
        if not m.get("centroid") or cid not in sizes or cluster_model(m) != model:
            continue
        p = (_unit(m["centroid"]) - mu) @ comp.T / scale
        cl.append({"cluster_id": cid, "label": m.get("label"), "topic": m.get("topic"), "size": sizes[cid],
                   "x": round(float(p[0]), 4), "y": round(float(p[1]), 4)})
    return {"project_id": pid, "days": days, "method": "pca", "embedding_model": model, "explained_variance": explained, "points": pts, "clusters": cl}
