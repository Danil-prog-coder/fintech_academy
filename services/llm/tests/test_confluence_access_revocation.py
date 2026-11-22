"""A received tombstone/scope removal withdraws published evidence without a reindex."""
import base64
import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import rag_service.api.app as api
from rag_service import confluence_source
from rag_service.agent.memory import SessionMemory
from rag_service.cache import ExactCache
from rag_service.config import get_settings
from rag_service.faq.service import FaqService
from rag_service.index import store
from rag_service.ingest import pipeline
from rag_service.retrieval import kb, search
from rag_service.retrieval.access import answer_allowed
from tests.fakes import FakeEmbedder


@pytest.mark.parametrize("withdrawal", ["tombstone", "scope"])
def test_withdrawal_blocks_search_links_images_caches_and_history(monkeypatch, tmp_path, withdrawal):
    pid = "withdraw-" + uuid.uuid4().hex[:8]
    settings = get_settings()
    for key, value in {"state_dir": str(tmp_path / "state"), "kb_dir": str(tmp_path / "uploads"),
                       "default_project_id": pid, "qdrant_collection": pid,
                       "confluence_sources": json.dumps({"team": {"project_id": pid}})}.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(pipeline, "get_embedder", FakeEmbedder)
    monkeypatch.setattr(search, "get_embedder", FakeEmbedder)
    image = io.BytesIO()
    Image.new("RGB", (60, 40), "red").save(image, format="PNG")
    page = {"document_id": "team:page:1", "page_id": "1", "title": "Private guide",
            "content_html": '<p>WITHDRAWN731</p><ac:image><ri:attachment ri:filename="screen.png"/></ac:image>',
            "attachments": [{"attachment_id": "image1", "filename": "screen.png", "has_data": True,
                             "content_base64": base64.b64encode(image.getvalue()).decode()}]}

    def receive(seq, doc):
        confluence_source.receive_batch("team", {"source_id": "team", "batch_id": str(seq),
            "source_sequence": seq, "source_binding": "test", "documents": [doc]})

    receive(1, page)
    manual = tmp_path / "manual.md"
    manual.write_text("# Public manual\n\nPUBLIC941", encoding="utf-8")
    result = pipeline.ingest([manual], pid, describe=False, include_git=False)
    assert result["status"] == "ok"
    manifest = store.active_manifest(pid)
    doc_id = next(d["doc_id"] for d in manifest["documents"] if d["source_type"] == "confluence")
    manual_id = next(d["doc_id"] for d in manifest["documents"] if d["source_type"] != "confluence")
    assert doc_id in kb.get_kb(pid)["docs"]  # Warm the in-process KB cache before withdrawal.
    image_id = next(iter(kb.get_kb(pid)["images"]))
    client = TestClient(api.app)
    assert client.get(f"/documents/{doc_id}/view", params={"project_id": pid}).status_code == 200
    cache = ExactCache()
    answer = {"action": "answer", "confidence_level": "high", "text": "WITHDRAWN731",
              "sources": [{"doc_id": doc_id}], "image_ids": [image_id]}
    cache.store(pid, result["generation"], "Как найти регламент?", answer)
    assert cache.lookup(pid, result["generation"], "Как найти регламент?")
    faq = FaqService()
    entry = {"enabled": True, "generation": result["generation"], "answer": answer}
    monkeypatch.setattr(faq, "load", lambda _: {"entries": {"cached": entry}})
    # A revoked entry must be eliminated before semantic search/embeddings are called.
    def forbid_faq_embedding(_):
        raise AssertionError("revoked FAQ must not be searched")
    monkeypatch.setattr(faq, "embed", forbid_faq_embedding)
    memory = SessionMemory()
    session = memory.load("s1", pid)
    session["messages"] = [{"role": "assistant", "content": "WITHDRAWN731"}]
    session["registry"] = {"S1": {"doc_id": doc_id, "text": "WITHDRAWN731"}}
    session["summary"] = "WITHDRAWN731"
    memory.save(session)
    idle = dict(session, session_id="idle")
    memory.save(idle)

    if withdrawal == "tombstone":
        receive(2, dict(page, deleted=True, delete_reason="visibility_revoked", attachments=[]))
    else:
        monkeypatch.setattr(settings, "confluence_sources", "{}")
    assert store.active_generation(pid) == result["generation"], "No manual publication has happened"
    # A fresh import/module instance must see the disk policy too, not rely on callback invalidation.
    assert confluence_source.denied_documents(pid, manifest) == {doc_id}
    visible = kb.get_kb(pid)
    assert doc_id not in visible["docs"] and manual_id in visible["docs"]
    assert image_id not in visible["images"]
    candidates = search.hybrid_candidates(pid, "WITHDRAWN731")
    assert all(c["doc_id"] != doc_id for c in candidates)
    assert client.get(f"/documents/{doc_id}/view", params={"project_id": pid}).status_code == 404
    assert client.get(f"/documents/{doc_id}/outline", params={"project_id": pid}).status_code == 404
    assert client.get(f"/images/{image_id}", params={"project_id": pid}).status_code == 404
    assert cache.lookup(pid, result["generation"], "Как найти регламент?") is None
    assert not answer_allowed(pid, answer)
    assert faq.lookup(pid, result["generation"], "Как найти регламент?") is None
    assert not answer_allowed(pid, {"sources": [{"source_id": "S1"}]})  # Unverifiable legacy cache.
    assert answer_allowed(pid, {"sources": [{"doc_id": manual_id}]})
    resumed = memory.load("s1", pid)
    assert not resumed["messages"] and not resumed["summary"] and not resumed["registry"]
    after = pipeline.ingest([manual], pid, describe=False, include_git=False)
    assert after["status"] == "ok"
    assert not memory.load("idle", pid)["messages"], "Idle sessions cannot regain old evidence after publication"
