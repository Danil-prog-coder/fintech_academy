"""search_docs core: dense + BM25 (Qdrant) -> RRF -> LLM rerank -> top-k with confidence signals."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from qdrant_client import models as qm

from ..config import get_settings
from ..index import store
from ..index.embeddings import get_embedder
from ..index.sparse import query_sparse
from .access import denied
from .kb import get_kb, match_document
from .rerank import llm_rerank

log = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=8)


def hybrid_candidates(project_id: str, query: str, *, doc_id: str | None = None, section_prefix: str | None = None,
                      chunk_types: list[str] | None = None, limit: int | None = None, timing: dict | None = None) -> list[dict]:
    s = get_settings()
    gen = store.active_generation(project_id)
    if not gen:
        return []
    limit = limit or s.candidate_k
    extra: list[qm.Condition] = []
    if doc_id:
        extra.append(qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id)))
    if chunk_types:
        extra.append(qm.FieldCondition(key="chunk_type", match=qm.MatchAny(any=chunk_types)))
    flt = store.base_filter(project_id, gen, extra)
    blocked = denied(project_id)
    if blocked:
        flt.must_not = [qm.FieldCondition(key="doc_id", match=qm.MatchAny(any=sorted(blocked)))]
    c = store.get_client()
    emb = get_embedder()

    tm: dict = {}

    def dense():
        t = time.time()
        v = emb.embed_query(query, timeout=s.retrieval_dense_timeout_s or None) if s.retrieval_dense_timeout_s else emb.embed_query(query)
        tm["embed_ms"] = int((time.time() - t) * 1000)
        pts = c.query_points(s.qdrant_collection, query=v, using=store.DENSE, query_filter=flt, limit=limit, with_payload=True).points
        tm["dense_ms"] = int((time.time() - t) * 1000)
        return pts

    def sparse():
        t = time.time()
        idx, val = query_sparse(query)
        if not idx:
            return []
        pts = c.query_points(s.qdrant_collection, query=qm.SparseVector(indices=idx, values=val), using=store.SPARSE,
                             query_filter=flt, limit=limit, with_payload=True).points
        tm["sparse_ms"] = int((time.time() - t) * 1000)
        return pts

    fd, fs = _pool.submit(dense), _pool.submit(sparse)
    if s.retrieval_dense_timeout_s:
        try:  # the embedding API is slow / down: BM25 alone rather than a minute-long wait
            dres = fd.result()
        except Exception as e:  # noqa: BLE001
            log.warning("dense search failed (%s), BM25 only", str(e)[:120])
            dres, tm["dense_failed"] = [], True
    else:
        dres = fd.result()
    sres = fs.result()
    if timing is not None:
        timing.update(tm)
    fused: dict[str, dict] = {}
    for rank, p in enumerate(dres):
        d = fused.setdefault(p.payload["chunk_id"], {**p.payload, "rrf": 0.0, "dense": None, "sparse": None})
        d["rrf"] += 1.0 / (s.rrf_k + rank + 1)
        d["dense"] = round(float(p.score), 4)
    for rank, p in enumerate(sres):
        d = fused.setdefault(p.payload["chunk_id"], {**p.payload, "rrf": 0.0, "dense": None, "sparse": None})
        d["rrf"] += 1.0 / (s.rrf_k + rank + 1)
        d["sparse"] = round(float(p.score), 4)
    out = sorted(fused.values(), key=lambda x: -x["rrf"])
    if section_prefix:
        sp = section_prefix.lower()
        pref = [x for x in out if sp in x["section_path_str"].lower()]
        out = pref + [x for x in out if x not in pref]
    return out[:limit]


def search(project_id: str, query: str, *, document: str | None = None, section: str | None = None,
           chunk_types: list[str] | None = None, top_k: int | None = None, rerank: bool | None = None) -> dict:
    s = get_settings()
    t0 = time.time()
    kb = get_kb(project_id)
    notes: list[str] = []
    doc_id = None
    if document:
        doc_id, score = match_document(kb, document)
        if not doc_id:
            notes.append(f"Документ «{document}» в базе знаний не найден. Доступные документы: "
                         + "; ".join(f"«{d['title']}»" for d in kb["docs"].values()) + ". Поиск выполнен по всей базе.")
    timing: dict = {}
    cands = hybrid_candidates(project_id, query, doc_id=doc_id, section_prefix=section, chunk_types=chunk_types, timing=timing)
    top_k = top_k or s.context_top_k
    do_rerank = (s.rerank_mode == "llm") if rerank is None else rerank
    t_rr = time.time()
    scores = llm_rerank(query, cands) if (do_rerank and cands) else None
    timing["rerank_ms"] = int((time.time() - t_rr) * 1000)
    timing["reranked"] = scores is not None
    if scores is not None:
        for c, sc in zip(cands, scores):
            c["rerank"] = round(sc, 3)
        cands.sort(key=lambda x: (-x["rerank"], -x["rrf"]))
        score_key = "rerank"
    else:
        # no reranker: normalised dense cosine as the evidence score
        for c in cands:
            c["rerank"] = None
        score_key = "dense"
    results = cands[:top_k]
    top_scores = [r.get(score_key) or 0.0 for r in results]
    signals = {
        "score_source": score_key,
        "max_score": round(top_scores[0], 3) if top_scores else 0.0,
        "gap_top1_top2": round(top_scores[0] - top_scores[1], 3) if len(top_scores) > 1 else (round(top_scores[0], 3) if top_scores else 0.0),
        "n_supporting": sum(1 for x in top_scores if x >= 0.6),
        "candidates": len(cands),
        "latency_ms": int((time.time() - t0) * 1000),
        "timing": timing,
    }
    return {"results": results, "signals": signals, "notes": notes, "doc_filter": doc_id}


class HybridRetriever:
    """HybridRetriever (Miro S97): dense + BM25 → RRF, filter by project_id + active generation; Reranker (S101)."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    def search(self, query: str, **kw) -> dict:
        return search(self.project_id, query, **kw)
