"""Answer-based clustering features (ANSWER_CLUSTERS_ENABLED): questions are grouped by what the bot answered, not only
by how they were worded. Two questions with different words but the same cited sections and a similar answer are one
need; two similar-looking questions answered from different sections are not.

Representation of one turn (all vectors are unit, so a dot product is a weighted cosine):

* `answer_text` — the answer without the sources block and citation markers, embedded with the same embedder as the
  questions (analytics/embedder.py: gemini-embedding-001, bge-m3 fallback);
* `source_vector` — hashed bag of cited sources: document (weight 0.5), section path (1.0), chunk id (1.0); a turn
  without sources gets an outcome token instead («no_facts», «escalate», …), so refusals are similar to each other;
* `combine([(vec, w), …])` — concatenation of √w·v, renormalised: dot(combine(a), combine(b)) = Σ w·cos(aᵢ, bᵢ) / Σ w.

The comparison of question / answer / hybrid clustering on the golden log is eval/clustering/answer_clusters.py.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import Counter

import numpy as np

SOURCE_DIM = 512
_SOURCES_BLOCK = re.compile(r"\n+\s*(?:\*\*)?Источники(?:\*\*)?\s*:.*\Z", re.S | re.I)
_MARKERS = re.compile(r"\[\d+\]")


def answer_text(text: str | None, limit: int = 2000) -> str:
    """The answer as a statement: without the «Источники:» block, [N] markers and markdown emphasis."""
    t = _SOURCES_BLOCK.sub("", text or "")
    t = _MARKERS.sub("", t).replace("**", "").replace("__", "")
    return re.sub(r"[ \t]+", " ", t).strip()[:limit]


def outcome_token(action: str | None, reason: str | None, n_sources: int) -> str | None:
    """A turn without sources: what happened instead (refusal, hand-off, clarification)."""
    if n_sources:
        return None
    if action in ("escalate", "offer_operator"):
        return "escalate"
    if action == "clarify":
        return "clarify"
    return (reason or "no_sources") if (reason or "").startswith(("no_facts", "guardrail")) else "no_sources"


def source_keys(sources: list | None) -> list[tuple[str, float]]:
    """(feature, weight) of the cited sources: document 0.5, section path 1.0, chunk 1.0."""
    out: list[tuple[str, float]] = []
    for s in sources or []:
        if not s:
            continue
        if isinstance(s, str):  # the turn log keeps only «Документ → раздел → подраздел» (query_logger.py)
            s = {"section_path": s, "document_title": s.split("→")[0].strip()}
        doc = s.get("document_title") or s.get("document") or s.get("doc_id")
        sec = s.get("section_path") or s.get("section")
        if isinstance(sec, list):
            sec = " → ".join(sec)
        if doc:
            out.append((f"d:{doc}", 0.5))
        if sec:
            out.append((f"s:{doc}|{sec}", 1.0))
        if s.get("chunk_id"):
            out.append((f"c:{s['chunk_id']}", 1.0))
    return out


def _h(feature: str) -> int:
    return int.from_bytes(hashlib.md5(feature.encode("utf-8")).digest()[:4], "little") % SOURCE_DIM


def source_vector(sources: list | None, action: str | None = None, reason: str | None = None) -> np.ndarray:
    v = np.zeros(SOURCE_DIM, dtype=np.float32)
    keys = source_keys(sources)
    w: Counter = Counter()
    for f, wt in keys:
        w[f] = max(w[f], wt)  # a section cited twice is still one section
    for f, wt in w.items():
        v[_h(f)] += wt
    tok = outcome_token(action, reason, len(sources or []))
    if tok:
        v[_h(f"o:{tok}")] += 1.0
    n = float(np.linalg.norm(v))
    return v / n if n else v


def section_set(sources: list | None) -> frozenset[str]:
    return frozenset(f for f, _ in source_keys(sources) if f.startswith("s:"))


def combine(parts: list[tuple[np.ndarray | None, float]]) -> np.ndarray:
    """Concatenate √w·v (each v unit or zero) and renormalise; a missing part is zeros of its usual size."""
    vs = []
    for v, wt in parts:
        a = np.asarray(v, dtype=np.float32)
        n = float(np.linalg.norm(a))
        vs.append((a / n if n else a) * np.sqrt(wt))
    out = np.concatenate(vs)
    n = float(np.linalg.norm(out))
    return out / n if n else out


def jaccard(a: frozenset, b: frozenset) -> float | None:
    if not a and not b:
        return None
    return len(a & b) / len(a | b)


def source_consistency(groups: list[list[frozenset]]) -> float | None:
    """Mean pairwise Jaccard of cited sections inside each group (pairs where at least one side cited something):
    the same kind of question should be answered from the same sections. None when nothing to compare."""
    vals = []
    for g in groups:
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                x = jaccard(g[i], g[j])
                if x is not None:
                    vals.append(x)
    return round(sum(vals) / len(vals), 4) if vals else None


# ---------------------------------------------------------------------------------------------- service side
def _unanswered(row: dict, turn: dict) -> bool:
    d = row.get("data") or {}
    if d.get("unanswered") is not None:
        return bool(d["unanswered"])
    return bool(turn.get("action") not in ("answer", "clarify") or (turn.get("reason") or "") in ("no_facts", "partial_answer")
                or turn.get("confidence_level") == "low")


def _turns(request_ids: set[str], project_id: str, days: float) -> dict[str, dict]:
    from .store import load_turns

    return {t["request_id"]: t for t in load_turns(days, project_id) if t.get("request_id") in request_ids}


def build(project_id: str | None = None, days: float = 30, rows: list[dict] | None = None, top: int = 10) -> dict:
    """Answer clusters over clusterable questions of the window (or the given `rows` of rag_questions):
    hybrid vector = ANSWER_CLUSTER_QUESTION_WEIGHT·question + the rest split between answer text and cited sections,
    clustered with the production algorithm. Feeds:
      * `faq_candidates` — ≥ ANSWER_FAQ_MIN_SIZE questions, ≥ ANSWER_FAQ_MIN_ANSWERED answered, cited sections consistent
        (≥ ANSWER_FAQ_MIN_CONSISTENCY): one need with one answer → FAQ / cache entry;
      * `gaps` — clusters where ≥ QUESTION_GAP_SHARE of the answers are refusals / hand-offs / low confidence;
      * `merge_suggestions` — one answer cluster spanning several question clusters (same need, different wording);
      * `answer_consistency` — inside each question cluster, mean pairwise Jaccard of cited sections: the same question
        type should be answered from the same sections (a judge / quality metric; low → unstable answers).
    Computed on demand from rag_questions + the turn log; embeddings come from the disk cache after the first call."""
    import sqlalchemy as sa

    from .. import db
    from ..config import get_settings
    from .embedder import embed, main_model, thresholds
    from .questions import QuestionClusters, _who, clusterable, entity_key

    s = get_settings()
    pid = project_id or s.default_project_id
    if not s.answer_clusters_enabled:
        return {"enabled": False, "project_id": pid}
    if rows is None:
        Q = db.questions
        rows = db.rows(sa.select(Q).where(Q.c.project_id == pid, Q.c.ts >= time.time() - days * 86400).order_by(Q.c.ts))
    rows = [r for r in rows if clusterable(r)]
    span = max(days, (time.time() - min((r["ts"] for r in rows), default=0)) / 86400 + 1) if rows else days
    turns = _turns({r["request_id"] for r in rows}, pid, span)
    rows = [r for r in rows if r["request_id"] in turns]
    out = {"enabled": True, "project_id": pid, "days": days, "questions": len(rows), "groups": 0, "faq_candidates": [],
           "gaps": [], "merge_suggestions": [], "answer_consistency": {"overall": None, "lowest": []}}
    if not rows:
        return out
    tr = [turns[r["request_id"]] for r in rows]
    atexts = [answer_text(t.get("answer")) or "(пустой ответ)" for t in tr]
    vecs, model = embed([r["text"] for r in rows] + atexts)
    n = len(rows)
    beta = s.answer_cluster_question_weight
    X = [combine([(vecs[i], beta), (vecs[n + i], (1 - beta) / 2),
                  (source_vector(tr[i].get("sources"), tr[i].get("action"), tr[i].get("reason")), (1 - beta) / 2)]) for i in range(n)]
    th = thresholds(model)["cluster"]
    if s.answer_cluster_threshold:  # calibrated on the main embedder; the fallback keeps the same offset from its own scale
        th = s.answer_cluster_threshold if model == main_model() else th + s.answer_cluster_threshold - s.question_cluster_threshold
    keys = [entity_key(r["text"]) for r in rows] if s.question_entity_guard else None
    groups = QuestionClusters.group(X, th, min(1.01, th + 0.04), s.question_min_cluster_size, s.question_refine_passes, keys)
    secs = [section_set(t.get("sources")) for t in tr]
    items = []
    for k, g in enumerate(groups):
        cent = np.sum([X[i] for i in g], axis=0)
        med = g[int(np.argmax([float(X[i] @ cent) for i in g]))]
        un = [i for i in g if _unanswered(rows[i], tr[i])]
        qcl = Counter(rows[i].get("cluster_id") for i in g if rows[i].get("cluster_id"))
        sec = Counter(x for i in g for x in secs[i])
        cons = source_consistency([[secs[i] for i in g]])
        answered = 1 - len(un) / len(g)
        items.append({
            "answer_cluster": f"a{k}", "count": len(g), "people": len({_who(rows[i]) for i in g}),
            "question": rows[med]["text"], "answer": atexts[med][:400],
            "examples": list(dict.fromkeys(rows[i]["text"] for i in g))[:5],
            "question_clusters": dict(qcl.most_common()), "sections": [x.split("|", 1)[-1] for x, _ in sec.most_common(3)],
            "answered_share": round(answered, 3), "unanswered": len(un), "source_consistency": cons,
            "outcomes": dict(Counter(tr[i].get("reason") or tr[i].get("action") for i in g).most_common(4)),
            "faq_candidate": bool(len(g) >= s.answer_faq_min_size and answered >= s.answer_faq_min_answered
                                  and (cons or 0) >= s.answer_faq_min_consistency),
            "gap": bool(len(un) / len(g) >= s.question_gap_share),
            "request_ids": [rows[i]["request_id"] for i in g][:50]})
    items.sort(key=lambda x: (-x["people"], -x["count"]))
    by_qc: dict[str, list[frozenset]] = {}
    for r, sc in zip(rows, secs):
        if r.get("cluster_id"):
            by_qc.setdefault(r["cluster_id"], []).append(sc)
    per = [{"cluster_id": cid, "count": len(v), "consistency": source_consistency([v])} for cid, v in by_qc.items() if len(v) >= 2]
    per = [p for p in per if p["consistency"] is not None]
    out.update({
        "groups": len(items), "embedding_model": model, "threshold": th,
        "faq_candidates": [x for x in items if x["faq_candidate"]][:top],
        "gaps": sorted((x for x in items if x["gap"]), key=lambda x: (-x["unanswered"], -x["count"]))[:top],
        "merge_suggestions": [{k: x[k] for k in ("answer_cluster", "question", "count", "question_clusters", "sections")}
                              for x in items if len(x["question_clusters"]) >= 2][:top],
        "answer_consistency": {"overall": source_consistency(list(by_qc.values())),
                               "lowest": sorted(per, key=lambda p: p["consistency"])[:top]},
    })
    return out
