"""Vector index of FAQ cache formulations in a separate Qdrant collection (FR-FAQ-03/04).

One point per question formulation (canonical + paraphrases). Payload: project_id, entry_id, generation,
enabled — so a lookup is filtered by project and the active generation (FR-FAQ-05: key = project_id + generation).
"""

from __future__ import annotations

import logging

from qdrant_client import models as qm

from ..config import get_settings
from ..index import store
from ..ingest.util import stable_uuid

log = logging.getLogger(__name__)


class FaqIndex:
    def __init__(self) -> None:
        self.name = get_settings().faq_collection
        self._ready_dim: int | None = None

    def _ensure(self, dim: int) -> None:
        if self._ready_dim == dim:
            return
        c = store.get_client()
        if c.collection_exists(self.name):
            vecs = c.get_collection(self.name).config.params.vectors
            size = vecs.size if hasattr(vecs, "size") else None
            if size != dim:
                c.delete_collection(self.name)
        if not c.collection_exists(self.name):
            c.create_collection(self.name, vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE))
            for field in ("project_id", "entry_id", "generation"):
                try:
                    c.create_payload_index(self.name, field, qm.PayloadSchemaType.KEYWORD)
                except Exception:  # noqa: BLE001  (local mode)
                    pass
        self._ready_dim = dim

    def put(self, project_id: str, entry: dict, vectors: list[list[float]], formulations: list[str], entities: list[dict]) -> None:
        self.delete(project_id, entry["id"])
        if not vectors:
            return
        self._ensure(len(vectors[0]))
        pts = [qm.PointStruct(id=stable_uuid(project_id, "faq", entry["id"], str(i)), vector=v, payload={
            "project_id": project_id, "entry_id": entry["id"], "generation": entry.get("generation") or "",
            "enabled": bool(entry.get("enabled")), "question": q, "entities": e})
            for i, (v, q, e) in enumerate(zip(vectors, formulations, entities))]
        store.get_client().upsert(self.name, pts, wait=True)

    def delete(self, project_id: str, entry_id: str) -> None:
        c = store.get_client()
        if not c.collection_exists(self.name):
            return
        c.delete(self.name, points_selector=qm.FilterSelector(filter=qm.Filter(must=[
            qm.FieldCondition(key="project_id", match=qm.MatchValue(value=project_id)),
            qm.FieldCondition(key="entry_id", match=qm.MatchValue(value=entry_id))])), wait=True)

    def set_meta(self, project_id: str, entry_id: str, **payload) -> None:
        c = store.get_client()
        if not c.collection_exists(self.name):
            return
        c.set_payload(self.name, payload=payload, points=qm.FilterSelector(filter=qm.Filter(must=[
            qm.FieldCondition(key="project_id", match=qm.MatchValue(value=project_id)),
            qm.FieldCondition(key="entry_id", match=qm.MatchValue(value=entry_id))])), wait=True)

    def search(self, project_id: str, generation: str, vector: list[float], limit: int = 3,
               threshold: float = 0.0, only_enabled: bool = True) -> list[tuple[str, str, float, dict]]:
        """→ [(entry_id, formulation, score, entities)] best first."""
        c = store.get_client()
        if not c.collection_exists(self.name):
            return []
        must: list[qm.Condition] = [qm.FieldCondition(key="project_id", match=qm.MatchValue(value=project_id))]
        if generation:
            must.append(qm.FieldCondition(key="generation", match=qm.MatchValue(value=generation)))
        if only_enabled:
            must.append(qm.FieldCondition(key="enabled", match=qm.MatchValue(value=True)))
        try:
            res = c.query_points(self.name, query=vector, query_filter=qm.Filter(must=must), limit=limit * 3,
                                 with_payload=True, score_threshold=threshold or None).points
        except Exception as e:  # noqa: BLE001
            log.warning("faq index search failed: %s", e)
            return []
        out, seen = [], set()
        for p in res:
            eid = p.payload["entry_id"]
            if eid in seen:
                continue
            seen.add(eid)
            out.append((eid, p.payload.get("question", ""), float(p.score), p.payload.get("entities") or {}))
        return out[:limit]
