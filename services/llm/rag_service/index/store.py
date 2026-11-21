"""Qdrant store: dense + BM25 sparse named vectors, payload indexes, project/generation isolation.

Server mode (QDRANT_URL, docker-compose) per FR-RET-05; local embedded mode (QDRANT_PATH) for dev/tests.
Every query is filtered by project_id and the project's active generation (FR-RET-06, FR-ARCH-01).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from functools import lru_cache
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from ..config import get_settings

log = logging.getLogger(__name__)
DENSE = "dense"
SPARSE = "bm25"


@lru_cache
def get_client() -> QdrantClient:
    s = get_settings()
    if s.qdrant_url:
        return QdrantClient(url=s.qdrant_url, timeout=30)
    Path(s.qdrant_path).mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=s.qdrant_path)


_lock = threading.Lock()


def ensure_collection(dim: int) -> None:
    s = get_settings()
    c = get_client()
    name = s.qdrant_collection
    if c.collection_exists(name):
        info = c.get_collection(name)
        vecs = info.config.params.vectors
        cur = vecs[DENSE].size if isinstance(vecs, dict) else None
        if cur == dim:
            return
        n = c.count(name, exact=False).count
        if n and not s.allow_collection_recreate:
            # a different embedding dimension must never silently wipe every project's index
            raise RuntimeError(f"collection {name} has dim {cur} and {n} points, new embeddings have dim {dim}: "
                               "set ALLOW_COLLECTION_RECREATE=true (then reindex every project) or use another QDRANT_COLLECTION")
        log.warning("dense dim changed (%s -> %s): recreating collection", cur, dim)
        c.delete_collection(name)
    c.create_collection(
        name,
        vectors_config={DENSE: qm.VectorParams(size=dim, distance=qm.Distance.COSINE)},
        sparse_vectors_config={SPARSE: qm.SparseVectorParams(modifier=qm.Modifier.IDF)},
    )
    for field, schema in [
        ("project_id", qm.PayloadSchemaType.KEYWORD),
        ("generation", qm.PayloadSchemaType.KEYWORD),
        ("doc_id", qm.PayloadSchemaType.KEYWORD),
        ("chunk_type", qm.PayloadSchemaType.KEYWORD),
        ("section_key", qm.PayloadSchemaType.KEYWORD),
    ]:
        try:
            c.create_payload_index(name, field, schema)
        except Exception:  # local mode ignores payload indexes
            pass


def upsert(points: list[qm.PointStruct]) -> None:
    s = get_settings()
    c = get_client()
    for i in range(0, len(points), 64):
        c.upsert(s.qdrant_collection, points[i:i + 64], wait=True)


def base_filter(project_id: str, generation: str, extra: list[qm.Condition] | None = None) -> qm.Filter:
    must: list[qm.Condition] = [
        qm.FieldCondition(key="project_id", match=qm.MatchValue(value=project_id)),
        qm.FieldCondition(key="generation", match=qm.MatchValue(value=generation)),
    ]
    return qm.Filter(must=must + (extra or []))


def scroll_all(project_id: str, generation: str) -> list[dict]:
    s = get_settings()
    c = get_client()
    out, offset = [], None
    while True:
        pts, offset = c.scroll(s.qdrant_collection, scroll_filter=base_filter(project_id, generation), limit=256, offset=offset, with_payload=True)
        out.extend(p.payload for p in pts)
        if offset is None:
            break
    return out


def scroll_with_vectors(project_id: str, generation: str) -> list[tuple[dict, list[float]]]:
    """All points of a generation with their dense vectors (incremental re-indexing reuses them, FR-GIT-03)."""
    s = get_settings()
    c = get_client()
    out, offset = [], None
    while True:
        pts, offset = c.scroll(s.qdrant_collection, scroll_filter=base_filter(project_id, generation), limit=256, offset=offset,
                               with_payload=True, with_vectors=[DENSE])
        for p in pts:
            v = p.vector[DENSE] if isinstance(p.vector, dict) else p.vector
            out.append((p.payload, list(v)))
        if offset is None:
            break
    return out


def delete_generation(project_id: str, generation: str) -> None:
    s = get_settings()
    get_client().delete(s.qdrant_collection, points_selector=qm.FilterSelector(filter=base_filter(project_id, generation)))


# ---- project state: active generation + manifest (FR-ADM-07, FR-ING-08) ----

def _state_file(project_id: str) -> Path:
    p = Path(get_settings().state_dir) / "projects" / f"{project_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_state(project_id: str) -> dict:
    f = _state_file(project_id)
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"project_id": project_id, "active_generation": None, "generations": []}


def _write_state(project_id: str, st: dict) -> None:
    """Write-then-rename: a crash mid-write never leaves a truncated state file (the active generation pointer)."""
    tmp = _state_file(project_id).with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_state_file(project_id))


def publish_generation(project_id: str, generation: str, manifest: dict, keep: int = 2) -> None:
    """Atomic switch of the active generation; old generations beyond `keep` are deleted (rollback = previous)."""
    with _lock:
        st = load_state(project_id)
        st["generations"] = [g for g in st.get("generations", []) if g["generation"] != generation]
        st["generations"].append({"generation": generation, "published_at": time.time(), "manifest": manifest})
        st["active_generation"] = generation
        while len(st["generations"]) > keep:
            old = st["generations"].pop(0)
            try:
                delete_generation(project_id, old["generation"])
            except Exception as e:  # noqa: BLE001
                log.warning("cannot delete old generation %s: %s", old["generation"], e)
        _write_state(project_id, st)


def rollback(project_id: str) -> str | None:
    with _lock:
        st = load_state(project_id)
        gens = st.get("generations", [])
        if len(gens) < 2:
            return None
        st["active_generation"] = gens[-2]["generation"]
        _write_state(project_id, st)
        return st["active_generation"]


def active_generation(project_id: str) -> str | None:
    return load_state(project_id).get("active_generation")


def active_manifest(project_id: str) -> dict:
    st = load_state(project_id)
    g = st.get("active_generation")
    for item in st.get("generations", []):
        if item["generation"] == g:
            return item["manifest"]
    return {}
