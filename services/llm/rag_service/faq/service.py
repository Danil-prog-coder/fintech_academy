"""Frequent questions and the semantic answer cache — level 2 (FR-FAQ-01..08, РК-6).

* FR-FAQ-01 `recompute()`: standalone questions of the sliding window → embeddings → greedy clustering
  (cosine ≥ FAQ_CLUSTER_THRESHOLD, only within the same key-entity set, so «реестр мебели» and «реестр техники»
  never share a cluster) → canonical question (LLM, medoid fallback) → ranking by frequency with time decay → top-K.
* FR-FAQ-02 `stats()`: top-K with counts, trend, paraphrases, topic, outcomes, 👍/👎 and documentation places.
* FR-FAQ-03 `build_answer()`: the full agent pipeline answers the canonical question; cached only when the
  final action is `answer` with high confidence, the citation check passed and the cluster has no 👎 majority.
* FR-FAQ-04 `lookup()`: embedding ≥ FAQ_MATCH_THRESHOLD → same key entities → cheap LLM equivalence check.
* FR-FAQ-05 `on_generation_change()` / TTL / 👎 threshold / drop-out from top-K; key = project_id + generation.
* FR-FAQ-08 manual entries: create / edit / delete (+ «не кэшировать» stop-list) / history / restore.

State (entries, stop-list, history, last cluster snapshot) is a JSON file per project in STATE_DIR/faq;
the vectors live in the Qdrant collection FAQ_COLLECTION (see index.py).
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
import uuid
from collections import Counter
from pathlib import Path

import numpy as np

from ..cache import normalize_question
from ..config import get_settings
from ..index import store
from ..index.embeddings import get_embedder
from ..llm import LLMUnavailable, chat, json_content
from .entities import entity_key, extract_entities, same_entities, title_vocabulary
from .index import FaqIndex

log = logging.getLogger(__name__)
STORED_FIELDS = ("action", "text", "sources", "image_ids", "confidence", "confidence_level", "reason", "buttons", "prompt_version")
PUBLIC_ENTRY_FIELDS = ("id", "question", "paraphrases", "answer", "origin", "enabled", "status", "flags", "generation",
                       "doc_versions", "created_at", "updated_at", "expires_at", "served", "likes", "dislikes", "entities",
                       "cluster_id", "updated_by")


def _now() -> float:
    return time.time()


def _unit(v) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(a)) or 1.0
    return a / n


class FaqService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._build_lock = threading.Lock()
        self.index = FaqIndex()
        self._eq_cache: dict[tuple[str, str], bool] = {}

    # ------------------------------------------------------------------ state
    def _path(self, project_id: str) -> Path:
        p = Path(get_settings().state_dir) / "faq" / f"{project_id}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def load(self, project_id: str) -> dict:
        p = self._path(project_id)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {"project_id": project_id, "entries": {}, "stoplist": [], "history": [], "clusters": [], "recomputed_at": None}

    def save(self, project_id: str, st: dict) -> None:
        p = self._path(project_id)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)

    def _vocab(self, project_id: str) -> set[str]:
        docs = store.active_manifest(project_id).get("documents", [])
        return title_vocabulary([d.get("title", "") for d in docs])

    @staticmethod
    def embed(texts: list[str]) -> list[list[float]]:
        emb = get_embedder()
        return emb._embed([f"query: {t}" if emb.is_e5 else t for t in texts])

    def _formulations(self, entry: dict) -> list[str]:
        return list(dict.fromkeys([entry["question"], *(entry.get("paraphrases") or [])]))[:12]

    def _index_entry(self, project_id: str, entry: dict) -> None:
        forms = self._formulations(entry)
        vocab = self._vocab(project_id)
        self.index.put(project_id, entry, self.embed(forms), forms, [extract_entities(f, vocab) for f in forms])

    def _history(self, st: dict, entry_id: str, action: str, by: str | None, before: dict | None) -> None:
        st["history"].append({"ts": _now(), "entry_id": entry_id, "action": action, "by": by or "system",
                              "before": copy.deepcopy(before) if before else None})
        st["history"] = st["history"][-2000:]

    @staticmethod
    def _expired(e: dict) -> bool:
        return e.get("origin") == "auto" and bool(e.get("expires_at")) and e["expires_at"] < _now()

    def _doc_versions(self, project_id: str, sources: list[dict]) -> dict[str, str]:
        docs = {d["doc_id"]: d.get("content_hash") or d.get("document_version") for d in store.active_manifest(project_id).get("documents", [])}
        out = {}
        for s in sources or []:
            cid = s.get("chunk_id") or ""
            did = s.get("doc_id") or (cid.rsplit(":", 1)[0] if ":" in cid else None)
            if did:
                out[did] = docs.get(did)
        return out

    # ------------------------------------------------------------------ FR-FAQ-04: lookup
    def lookup(self, project_id: str, generation: str, question: str) -> dict | None:
        from ..retrieval.access import answer_allowed, denied

        s = get_settings()
        st = self.load(project_id)
        blocked = denied(project_id)
        live = {eid: e for eid, e in st["entries"].items() if e.get("enabled") and e.get("generation") == generation
                and not self._expired(e) and answer_allowed(project_id, e.get("answer") or {}, blocked)}
        if not live:
            return None  # nothing cached → no embedding call on the hot path
        q_ents = extract_entities(question, self._vocab(project_id))
        vec = self.embed([question])[0]
        for eid, form, score, ents in self.index.search(project_id, generation, vec, limit=3, threshold=s.faq_match_threshold):
            e = live.get(eid)
            if not e:
                continue
            if not same_entities(q_ents, ents):
                log.info("faq: entity mismatch %s vs %s", q_ents, ents)
                continue
            if s.faq_verify_llm and not self.equivalent(question, form):
                continue
            return {"entry": e, "score": round(score, 4), "matched": form}
        return None

    def equivalent(self, q1: str, q2: str) -> bool:
        """FR-FAQ-04 step 3: a cheap model confirms the two questions need the same answer. Unavailable → no hit."""
        n1, n2 = normalize_question(q1), normalize_question(q2)
        if n1 == n2:
            return True
        key = (min(n1, n2), max(n1, n2))
        if key in self._eq_cache:
            return self._eq_cache[key]
        verdict = self._equivalent_llm(q1, q2)
        if verdict is not None:
            if len(self._eq_cache) > 5000:
                self._eq_cache.clear()
            self._eq_cache[key] = verdict
        return bool(verdict)

    def _equivalent_llm(self, q1: str, q2: str) -> bool | None:
        s = get_settings()
        try:
            r = chat(model=s.faq_verify_model or s.rerank_model, retries=0, deadline=_now() + 6, temperature=0,
                     response_format={"type": "json_object"}, messages=[
                         {"role": "system", "content": "Ты проверяешь кэш ответов службы поддержки. Определи, равнозначны ли два вопроса: "
                          "подходит ли к ним один и тот же ответ из документации. Разные объекты (один документ, реестр или экран "
                          "вместо другого, пусть и с похожим названием), разные действия, разные условия или числа — НЕ равнозначны. "
                          "Верни строго JSON: {\"equivalent\": true|false}"},
                         {"role": "user", "content": f"Вопрос A: {q1}\nВопрос B: {q2}"}])
            return bool(json_content(r).get("equivalent"))
        except (LLMUnavailable, TimeoutError, json.JSONDecodeError, AttributeError, IndexError) as e:
            log.warning("faq equivalence check unavailable: %s", e)
            return None  # unknown → treated as «not equivalent», not cached

    def mark_served(self, project_id: str, entry_id: str) -> None:
        with self._lock:
            st = self.load(project_id)
            e = st["entries"].get(entry_id)
            if e:
                e["served"] = e.get("served", 0) + 1
                e["last_served_at"] = _now()
                self.save(project_id, st)

    # ------------------------------------------------------------------ FR-FAQ-05: 👎 on cached answers
    def feedback(self, project_id: str, entry_id: str, rating: str) -> dict | None:
        s = get_settings()
        with self._lock:
            st = self.load(project_id)
            e = st["entries"].get(entry_id)
            if not e:
                return None
            e["likes" if rating == "up" else "dislikes"] = e.get("likes" if rating == "up" else "dislikes", 0) + 1
            if e.get("dislikes", 0) >= s.faq_dislike_threshold and e["dislikes"] > e.get("likes", 0) and e.get("enabled"):
                e["enabled"] = False
                e["status"] = "disabled"
                e.setdefault("flags", []).append("too_many_dislikes")
                self.index.set_meta(project_id, entry_id, enabled=False)
                self._history(st, entry_id, "auto_disabled_dislikes", None, None)
            self.save(project_id, st)
            return e

    # ------------------------------------------------------------------ FR-FAQ-03: answers
    def build_answer(self, project_id: str, question: str) -> tuple[dict | None, str]:
        from ..agent.loop import run_turn_sync
        from ..agent.memory import get_memory

        sid = f"faq-build-{uuid.uuid4().hex[:10]}"
        try:
            res = run_turn_sync(sid, project_id, question, log_turn=False)
        finally:
            get_memory().reset(sid, project_id)
        if res.get("action") != "answer":
            return None, f"action={res.get('action')}"
        if res.get("confidence_level") != "high":
            return None, f"confidence={res.get('confidence_level')}"
        if not res.get("sources") or res.get("removed_quotes"):
            return None, "citation_check"
        return res, "ok"

    def _new_entry(self, project_id: str, question: str, answer: dict, origin: str, *, paraphrases: list[str] | None = None,
                   cluster_id: str | None = None, by: str | None = None) -> dict:
        s = get_settings()
        gen = store.active_generation(project_id)
        return {
            "id": uuid.uuid4().hex[:12], "project_id": project_id, "question": question.strip(),
            "paraphrases": [p for p in dict.fromkeys(paraphrases or []) if p and p != question][:10],
            "answer": {f: answer.get(f) for f in STORED_FIELDS}, "origin": origin, "enabled": True, "status": "active",
            "flags": [], "generation": gen, "doc_versions": self._doc_versions(project_id, answer.get("sources") or []),
            "entities": extract_entities(question, self._vocab(project_id)), "cluster_id": cluster_id,
            "created_at": _now(), "updated_at": _now(), "updated_by": by or "system",
            "expires_at": _now() + s.faq_auto_ttl_s if origin == "auto" else None,
            "served": 0, "likes": 0, "dislikes": 0,
        }

    # ------------------------------------------------------------------ FR-FAQ-01/02: clustering + stats
    @staticmethod
    def standalone_questions(recs: list[dict]) -> list[dict]:
        """First question of a session, or the agent's self-contained rewrite of a follow-up (its first search query)."""
        from ..agent.guardrails import is_operator_request
        from ..analytics.store import search_queries

        out = []
        for r in recs:
            if r.get("has_images"):
                continue
            text = (r.get("text") or "").strip()
            if not text or is_operator_request(text):
                continue
            if r.get("action") == "answer" and not r.get("sources") and not r.get("cache_hit"):
                continue  # small talk / polite refusal outside the topic: nothing to cache (FR-FAQ-01)
            if not r.get("standalone"):
                qs = search_queries(r)
                if not qs:
                    continue
                text = qs[0]
            if len(text) < 8:
                continue
            out.append({"text": text, "ts": r.get("ts", 0), "rec": r})
        return out

    def cluster(self, project_id: str, items: list[dict], threshold: float | None = None, use_llm: bool | None = None,
                max_llm_checks: int = 150) -> list[dict]:
        s = get_settings()
        threshold = threshold or s.faq_cluster_threshold
        use_llm = s.faq_verify_llm if use_llm is None else use_llm
        llm_budget = [max_llm_checks]
        if not items:
            return []
        vocab = self._vocab(project_id)
        vecs = [_unit(v) for v in self.embed([it["text"] for it in items])]
        clusters: list[dict] = []
        for i, it in enumerate(items):
            ents = extract_entities(it["text"], vocab)
            key = entity_key(ents)
            best, best_sim, grey = None, threshold, None
            for c in clusters:
                if c["ekey"] != key:
                    continue  # homogeneity: different objects/numbers/operators never share a cluster
                sim = float(np.dot(vecs[i], c["centroid"]))
                if sim >= best_sim:
                    best, best_sim = c, sim
                elif sim >= s.faq_cluster_grey and (grey is None or sim > grey[1]):
                    grey = (c, sim)
            if best is None and grey and use_llm and llm_budget[0] > 0:
                # grey zone: a cheap model decides whether the question is a paraphrase of the cluster's medoid
                llm_budget[0] -= 1
                head = items[grey[0]["members"][0]]["text"]
                if self.equivalent(it["text"], head):
                    best = grey[0]
            if best is None:
                best = {"ekey": key, "entities": ents, "members": [], "sum": np.zeros_like(vecs[i]), "centroid": vecs[i]}
                clusters.append(best)
            best["members"].append(i)
            best["sum"] = best["sum"] + vecs[i]
            best["centroid"] = _unit(best["sum"])
        now = _now()
        out = []
        for c in clusters:
            members = [items[i] for i in c["members"]]
            mv = np.stack([vecs[i] for i in c["members"]])
            medoid = members[int(np.argmax(mv @ c["centroid"]))]["text"]
            texts = [m["text"] for m in members]
            weight = sum(0.5 ** ((now - m["ts"]) / 86400 / s.faq_half_life_days) for m in members)
            out.append({"members": members, "texts": texts, "canonical": medoid, "entities": c["entities"],
                        "centroid": c["centroid"], "count": len(members), "weight": round(weight, 3)})
        out.sort(key=lambda c: (-c["weight"], -c["count"]))
        return out

    def canonical(self, texts: list[str], fallback: str, entities: dict, vocab: set[str]) -> str:
        if not get_settings().faq_canonical_llm or len(set(texts)) < 2:
            return fallback
        s = get_settings()
        try:
            r = chat(model=s.summary_model, retries=0, deadline=_now() + 15, temperature=0, response_format={"type": "json_object"},
                     messages=[{"role": "system", "content": "Тебе дан список формулировок одного вопроса пользователей службы поддержки. "
                                "Сформулируй один каноничный самостоятельный вопрос на русском: кратко, без опечаток, сохрани все объекты, "
                                "числа и операторы. Верни строго JSON: {\"question\": \"...\"}"},
                               {"role": "user", "content": "\n".join(f"- {t}" for t in list(dict.fromkeys(texts))[:15])}])
            q = str(json_content(r).get("question") or "").strip()
            if q and same_entities(extract_entities(q, vocab), entities):
                return q
        except (LLMUnavailable, TimeoutError, json.JSONDecodeError, AttributeError, IndexError) as e:
            log.info("faq canonical fallback: %s", e)
        return fallback

    def recompute(self, project_id: str, *, build: bool = True, days: int | None = None, top_k: int | None = None) -> dict:
        """FR-FAQ-01..03/05: re-cluster the window, refresh stats, (re)build auto answers, drop stale auto entries."""
        from ..analytics.classify import get_classifier
        from ..analytics.store import load_feedback, load_turns

        s = get_settings()
        t0 = _now()
        days = days or s.faq_window_days
        top_k = top_k or s.faq_top_k
        recs = load_turns(days, project_id)
        fb = load_feedback()
        classes = get_classifier().load()
        vocab = self._vocab(project_id)
        clusters = self.cluster(project_id, self.standalone_questions(recs))
        if s.question_user_ref_enabled:  # rank by distinct people (user_ref, else session) instead of raw count
            from ..analytics.questions import people_by_request

            who = people_by_request([m["rec"].get("request_id") for c in clusters for m in c["members"] if m["rec"].get("request_id")])
            for c in clusters:
                c["people"] = len({who.get(m["rec"].get("request_id")) or m["rec"].get("session") for m in c["members"]})
            clusters.sort(key=lambda c: (-c["people"], -c["weight"], -c["count"]))
        frequent = [c for c in clusters if c["count"] >= s.faq_min_cluster_size][:top_k]
        gen = store.active_generation(project_id)
        with self._lock:
            st = self.load(project_id)
        stop_vecs = [(_unit(v), it) for v, it in zip(self.embed([x["question"] for x in st["stoplist"]]), st["stoplist"])] if st["stoplist"] else []
        snapshot, report = [], {"built": [], "build_failed": [], "removed": [], "kept_manual": [], "rebuilt_expired": []}
        top_entry_ids: set[str] = set()
        for rank, c in enumerate(frequent, 1):
            c["canonical"] = self.canonical(c["texts"], c["canonical"], c["entities"], vocab)
            stats = self._cluster_stats(c, fb, classes)
            stop = next((it for v, it in stop_vecs if float(np.dot(v, c["centroid"])) >= s.faq_match_threshold
                         and same_entities(it.get("entities") or {}, c["entities"])), None)
            hits = self.index.search(project_id, "", c["centroid"].tolist(), limit=3, threshold=s.faq_match_threshold, only_enabled=False)
            entry_id = next((eid for eid, _, _, ents in hits if eid in st["entries"] and same_entities(ents, c["entities"])), None)
            cid = entry_id or f"c{uuid.uuid5(uuid.NAMESPACE_URL, normalize_question(c['canonical'])).hex[:10]}"
            snapshot.append({"rank": rank, "cluster_id": cid, "canonical": c["canonical"], "count": c["count"], "weight": c["weight"],
                             "examples": list(dict.fromkeys(c["texts"]))[:5], "entities": c["entities"], "entry_id": entry_id,
                             "stoplisted": bool(stop), **stats})
            if stop:
                continue
            if entry_id:
                top_entry_ids.add(entry_id)
            e = st["entries"].get(entry_id) if entry_id else None
            bad = stats["dislikes"] >= 2 and stats["dislikes"] > stats["likes"]
            needs_build = (e is None or (e.get("origin") == "auto" and (self._expired(e) or e.get("status") == "stale"))) and not bad
            if build and needs_build and gen:
                with self._build_lock:
                    res, why = self.build_answer(project_id, c["canonical"])
                para = [t for t in dict.fromkeys(c["texts"]) if t != c["canonical"]][:8]
                with self._lock:
                    st = self.load(project_id)
                    if res:
                        old = st["entries"].pop(entry_id, None) if entry_id else None
                        ne = self._new_entry(project_id, c["canonical"], res, "auto", paraphrases=para, cluster_id=cid)
                        if old:
                            ne["id"] = old["id"]
                            ne["created_at"] = old.get("created_at", ne["created_at"])
                            report["rebuilt_expired"].append(old["id"])
                        st["entries"][ne["id"]] = ne
                        self._history(st, ne["id"], "auto_built" if not old else "auto_rebuilt", None, old)
                        self.save(project_id, st)
                        self._index_entry(project_id, ne)
                        top_entry_ids.add(ne["id"])
                        snapshot[-1]["entry_id"] = ne["id"]
                        report["built"].append(c["canonical"])
                    else:
                        report["build_failed"].append({"question": c["canonical"], "why": why})
        # FR-FAQ-05: auto entries of clusters that fell out of top-K (or expired) are removed; manual ones stay
        with self._lock:
            st = self.load(project_id)
            for eid, e in list(st["entries"].items()):
                if e.get("origin") == "manual":
                    report["kept_manual"].append(eid)
                    continue
                if eid not in top_entry_ids or self._expired(e):
                    st["entries"].pop(eid)
                    self.index.delete(project_id, eid)
                    self._history(st, eid, "auto_removed_out_of_top" if eid not in top_entry_ids else "auto_removed_ttl", None, e)
                    report["removed"].append(eid)
            st["clusters"] = snapshot
            st["recomputed_at"] = _now()
            st["window_days"] = days
            self.save(project_id, st)
        report.update({"status": "ok", "questions": sum(c["count"] for c in clusters), "clusters": len(clusters),
                       "top_k": len(frequent), "elapsed_s": round(_now() - t0, 1)})
        return report

    @staticmethod
    def _cluster_stats(c: dict, fb: dict, classes: dict) -> dict:
        from ..analytics.store import outcome

        now = _now()
        recs = [m["rec"] for m in c["members"]]
        outs = Counter(outcome(r) for r in recs)
        ratings = Counter(fb.get(r.get("request_id")) for r in recs)
        last24 = sum(1 for m in c["members"] if now - m["ts"] <= 86400)
        span_days = max(1.0, (now - min(m["ts"] for m in c["members"])) / 86400)
        prev_avg = (len(c["members"]) - last24) / max(1.0, span_days - 1)
        topics = Counter((classes.get(r.get("request_id")) or {}).get("topic") for r in recs)
        topics.pop(None, None)
        places: Counter = Counter()
        for r in recs:
            for sp in set(r.get("sources") or []):
                if sp:
                    places[sp] += 1
        n = len(recs)
        esc = outs.get("escalate", 0) + outs.get("offer_operator", 0)
        return {
            "trend": {"last_24h": last24, "prev_daily_avg": round(prev_avg, 2), "rising": last24 >= 3 and last24 > 2 * prev_avg},
            "topic": topics.most_common(1)[0][0] if topics else None,
            "outcomes": dict(outs), "answer_rate": round((outs.get("answer", 0) + outs.get("cache_answer", 0)) / n, 3) if n else None,
            "cache_share": round(outs.get("cache_answer", 0) / n, 3) if n else None,
            "escalation_rate": round(esc / n, 3) if n else None,
            "likes": ratings.get("up", 0), "dislikes": ratings.get("down", 0),
            "doc_places": places.most_common(5),
            # FR-FAQ-02 highlight: frequent question without a good answer → candidate for documentation (FR-AN-05)
            "needs_docs": n >= 2 and (esc + ratings.get("down", 0)) / n >= 0.3,
        }

    def stats(self, project_id: str) -> dict:
        st = self.load(project_id)
        clusters = st.get("clusters") or []
        return {"project_id": project_id, "recomputed_at": st.get("recomputed_at"), "window_days": st.get("window_days"),
                "top": clusters,
                "highlights": {
                    "rising": [c["canonical"] for c in clusters if (c.get("trend") or {}).get("rising")],
                    "needs_docs": [c["canonical"] for c in clusters if c.get("needs_docs")],
                },
                "entries": {"total": len(st["entries"]), "enabled": sum(1 for e in st["entries"].values() if e.get("enabled")),
                            "manual": sum(1 for e in st["entries"].values() if e.get("origin") == "manual"),
                            "needs_review": [e["id"] for e in st["entries"].values() if "sources_changed" in (e.get("flags") or [])]},
                "stoplist": st["stoplist"]}

    # ------------------------------------------------------------------ FR-FAQ-05: new knowledge-base version
    def on_generation_change(self, project_id: str, *, rebuild: bool = True) -> dict:
        gen = store.active_generation(project_id)
        cur = {d["doc_id"]: d.get("content_hash") or d.get("document_version") for d in store.active_manifest(project_id).get("documents", [])}
        rep = {"carried": [], "stale_auto": [], "manual_review": []}
        with self._lock:
            st = self.load(project_id)
            for eid, e in st["entries"].items():
                if e.get("generation") == gen:
                    continue
                changed = any(cur.get(d) != v for d, v in (e.get("doc_versions") or {}).items())
                if not changed:
                    e["generation"] = gen
                    self.index.set_meta(project_id, eid, generation=gen)
                    rep["carried"].append(eid)
                elif e.get("origin") == "auto":
                    e.update(enabled=False, status="stale")
                    self.index.set_meta(project_id, eid, enabled=False)
                    rep["stale_auto"].append(eid)
                else:
                    e.update(enabled=False, status="needs_review", generation=gen)
                    if "sources_changed" not in e.setdefault("flags", []):
                        e["flags"].append("sources_changed")  # panel: «Источники изменились — проверьте ответ»
                    self.index.set_meta(project_id, eid, enabled=False, generation=gen)
                    rep["manual_review"].append(eid)
                    self._history(st, eid, "manual_disabled_sources_changed", None, None)
            self.save(project_id, st)
        if rebuild and rep["stale_auto"]:
            threading.Thread(target=self._rebuild_stale, args=(project_id, rep["stale_auto"]), daemon=True).start()
        return rep

    def _rebuild_stale(self, project_id: str, ids: list[str]) -> None:
        for eid in ids:
            with self._lock:
                e = self.load(project_id)["entries"].get(eid)
            if not e or e.get("status") != "stale":
                continue
            try:
                with self._build_lock:
                    res, _ = self.build_answer(project_id, e["question"])
            except Exception as ex:  # noqa: BLE001
                log.warning("faq rebuild failed: %s", ex)
                res = None
            with self._lock:
                st = self.load(project_id)
                old = st["entries"].get(eid)
                if not old:
                    continue
                if res:
                    ne = self._new_entry(project_id, old["question"], res, "auto", paraphrases=old.get("paraphrases"), cluster_id=old.get("cluster_id"))
                    ne.update(id=eid, created_at=old.get("created_at"), served=old.get("served", 0))
                    st["entries"][eid] = ne
                    self._history(st, eid, "auto_rebuilt_sources_changed", None, old)
                    self.save(project_id, st)
                    self._index_entry(project_id, ne)
                else:
                    st["entries"].pop(eid)
                    self._history(st, eid, "auto_removed_rebuild_failed", None, old)
                    self.save(project_id, st)
                    self.index.delete(project_id, eid)

    # ------------------------------------------------------------------ FR-FAQ-08: manual management
    def list_entries(self, project_id: str) -> list[dict]:
        st = self.load(project_id)
        return sorted(({k: e.get(k) for k in PUBLIC_ENTRY_FIELDS} for e in st["entries"].values()), key=lambda e: -(e.get("served") or 0))

    def get_entry(self, project_id: str, entry_id: str) -> dict | None:
        return self.load(project_id)["entries"].get(entry_id)

    def similar(self, project_id: str, question: str, exclude: str | None = None) -> list[dict]:
        s = get_settings()
        vec = self.embed([question])[0]
        out = []
        st = self.load(project_id)
        for eid, form, score, _ in self.index.search(project_id, "", vec, limit=5, threshold=s.faq_cluster_threshold, only_enabled=False):
            if eid != exclude and eid in st["entries"]:
                out.append({"entry_id": eid, "question": form, "score": round(score, 3)})
        return out

    @staticmethod
    def _manual_answer(text: str, sources: list[dict] | None, support_answer: bool) -> dict:
        srcs = []
        for i, s in enumerate(sources or [], 1):
            srcs.append({"citation_label": f"[{i}]", "source_id": s.get("source_id") or f"M{i}", "chunk_id": s.get("chunk_id"),
                         "doc_id": s.get("doc_id"), "document_title": s.get("document_title") or "",
                         "section_path": s.get("section_path") or s.get("document_title") or "", "excerpt": s.get("excerpt") or "",
                         "chunk_type": s.get("chunk_type") or "text", "image_ids": s.get("image_ids") or [], "url": s.get("url")})
        if support_answer and not srcs:
            srcs = [{"citation_label": "[1]", "source_id": "M1", "document_title": "Ответ поддержки", "section_path": "Ответ поддержки",
                     "excerpt": "", "chunk_type": "tool", "image_ids": []}]
        return {"action": "answer", "text": text.strip(), "sources": srcs, "image_ids": [i for s in srcs for i in s.get("image_ids") or []][:3],
                "confidence": 1.0, "confidence_level": "high", "reason": "manual_faq", "buttons": [], "prompt_version": "manual"}

    def create_manual(self, project_id: str, question: str, text: str, *, paraphrases: list[str] | None = None,
                      sources: list[dict] | None = None, support_answer: bool = False, by: str | None = None) -> dict:
        warnings = [f"похожая запись уже есть: «{x['question']}» ({x['score']})" for x in self.similar(project_id, question)]
        e = self._new_entry(project_id, question, self._manual_answer(text, sources, support_answer), "manual", paraphrases=paraphrases, by=by)
        with self._lock:
            st = self.load(project_id)
            st["entries"][e["id"]] = e
            self._history(st, e["id"], "manual_created", by, None)
            self.save(project_id, st)
        self._index_entry(project_id, e)
        return {"entry": e, "warnings": warnings}

    def edit(self, project_id: str, entry_id: str, *, text: str | None = None, sources: list[dict] | None = None,
             paraphrases: list[str] | None = None, question: str | None = None, enabled: bool | None = None, by: str | None = None) -> dict | None:
        with self._lock:
            st = self.load(project_id)
            e = st["entries"].get(entry_id)
            if not e:
                return None
            before = copy.deepcopy(e)
            if question:
                e["question"] = question.strip()
                e["entities"] = extract_entities(e["question"], self._vocab(project_id))
            if paraphrases is not None:
                e["paraphrases"] = [p for p in dict.fromkeys(paraphrases) if p][:10]
            if text is not None or sources is not None:
                cur = e["answer"]
                new = self._manual_answer(text if text is not None else cur.get("text", ""),
                                          sources if sources is not None else cur.get("sources"), support_answer=False)
                if sources is None:
                    new["sources"], new["image_ids"] = cur.get("sources"), cur.get("image_ids")
                e["answer"] = new
                e["doc_versions"] = self._doc_versions(project_id, e["answer"].get("sources") or [])
            e.update(origin="manual", expires_at=None, updated_at=_now(), updated_by=by or "admin")  # never overwritten automatically
            if enabled is not None:
                e["enabled"] = enabled
                e["status"] = "active" if enabled else "disabled"
                if enabled:
                    e["flags"] = [f for f in e.get("flags") or [] if f != "sources_changed"]
                    e["generation"] = store.active_generation(project_id)
            self._history(st, entry_id, "manual_edited", by, before)
            self.save(project_id, st)
        self._index_entry(project_id, e)
        return e

    def delete(self, project_id: str, entry_id: str, *, no_cache: bool = False, by: str | None = None) -> bool:
        with self._lock:
            st = self.load(project_id)
            e = st["entries"].pop(entry_id, None)
            if not e:
                return False
            if no_cache:  # «Удалить и не кэшировать»: the cluster goes to the stop-list
                st["stoplist"].append({"id": uuid.uuid4().hex[:10], "question": e["question"], "entities": e.get("entities") or {},
                                       "added_at": _now(), "by": by or "admin"})
            self._history(st, entry_id, "deleted_no_cache" if no_cache else "deleted", by, e)
            self.save(project_id, st)
        self.index.delete(project_id, entry_id)
        return True

    def unstop(self, project_id: str, stop_id: str) -> bool:
        with self._lock:
            st = self.load(project_id)
            n = len(st["stoplist"])
            st["stoplist"] = [x for x in st["stoplist"] if x["id"] != stop_id]
            self.save(project_id, st)
            return len(st["stoplist"]) < n

    def history(self, project_id: str, entry_id: str | None = None) -> list[dict]:
        h = self.load(project_id)["history"]
        return [x for x in h if entry_id is None or x["entry_id"] == entry_id]

    def restore(self, project_id: str, entry_id: str, version: int, by: str | None = None) -> dict | None:
        """Restore the `version`-th saved snapshot (index in history(entry_id) with a `before`)."""
        snaps = [x for x in self.history(project_id, entry_id) if x.get("before")]
        if not (0 <= version < len(snaps)):
            return None
        snap = copy.deepcopy(snaps[version]["before"])
        with self._lock:
            st = self.load(project_id)
            cur = st["entries"].get(entry_id)
            snap.update(origin="manual", expires_at=None, updated_at=_now(), updated_by=by or "admin")
            st["entries"][entry_id] = snap
            self._history(st, entry_id, "restored", by, cur)
            self.save(project_id, st)
        self._index_entry(project_id, snap)
        return snap

    def clear(self, project_id: str, include_manual: bool = False) -> int:
        with self._lock:
            st = self.load(project_id)
            ids = [eid for eid, e in st["entries"].items() if include_manual or e.get("origin") != "manual"]
            for eid in ids:
                self._history(st, eid, "cleared", None, st["entries"].pop(eid))
            self.save(project_id, st)
        for eid in ids:
            self.index.delete(project_id, eid)
        return len(ids)

    def popular(self, project_id: str, limit: int = 5) -> list[str]:
        """FR-FAQ-07: popular questions for the bot menu / greeting."""
        st = self.load(project_id)
        return [c["canonical"] for c in st.get("clusters") or [] if not c.get("stoplisted")][:limit]


_faq: FaqService | None = None


def get_faq() -> FaqService:
    global _faq
    if _faq is None:
        _faq = FaqService()
    return _faq
