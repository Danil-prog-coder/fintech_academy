"""Real parsing/jobs/local Qdrant, deterministic embeddings; no Telegram or remote LLM."""

import base64
import hashlib
import io
import json
import uuid

from docx import Document
from fastapi.testclient import TestClient

import rag_service.api.app as api
from rag_service.core.config import get_settings
from rag_service.index import store
from rag_service.ingest import pipeline
from tests.fakes import FakeEmbedder


def test_new_docx_and_confluence_reach_search_only_after_publication(monkeypatch, tmp_path):
    settings = get_settings()
    pid = "publication-" + uuid.uuid4().hex[:8]
    for name, value in {"state_dir": str(tmp_path / "state"), "kb_dir": str(tmp_path / "uploads"),
                        "qdrant_collection": pid, "faq_enabled": False,
                        "confluence_sources": json.dumps({"team": {"project_id": pid}})}.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(pipeline, "get_embedder", FakeEmbedder)
    document = Document()
    document.add_heading("Проверочный регламент", 0)
    document.add_paragraph("Код проверки заявки: 7842.")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Срок"
    table.cell(0, 1).text = "3 дня"
    output = io.BytesIO()
    document.save(output)
    data = output.getvalue()
    client = TestClient(api.app)

    result = client.post("/documents", data={"project_id": pid},
                         files={"files": ("new.docx", data, "application/octet-stream")})
    assert result.status_code == 200 and result.json()["status"] == "staged"
    assert not store.active_generation(pid)

    def publish():
        job = client.post("/reindex", json={"project_id": pid, "wait": True, "describe_images": False})
        assert job.status_code == 200 and job.json()["status"] == "done", job.text
        generation = store.active_generation(pid)
        return generation, store.scroll_all(pid, generation)

    first, chunks = publish()
    assert any("7842" in c["text"] for c in chunks)
    assert any(c["chunk_type"] == "table" for c in chunks)
    hits = store.get_client().query_points(
        settings.qdrant_collection, query=FakeEmbedder().embed_query("Код проверки заявки 7842"),
        using=store.DENSE, query_filter=store.base_filter(pid, first), with_payload=True, limit=5).points
    assert any("7842" in hit.payload["text"] for hit in hits)

    doc = {"document_id": "team:page:1", "page_id": "1", "version": 1,
           "title": "Синтетическая Confluence-страница", "content_html": "<p>Маркер импорта ALPHA731.</p>",
           "source_url": "https://example.test/wiki/pages/1", "deleted": False,
           "attachments": [{"attachment_id": "word1", "filename": "attached.docx", "has_data": True,
                            "content_base64": base64.b64encode(data).decode(),
                            "sha256": hashlib.sha256(data).hexdigest()}]}
    def receive(sequence, page):
        response = client.post("/sources/team/batches", json={
            "batch_id": f"team:{sequence}", "source_id": "team", "source_sequence": sequence,
            "source_binding": "test-binding", "documents": [page]})
        assert response.status_code == 200, response.text
        assert response.json()["job_id"] is None

    receive(1, doc)
    assert store.active_generation(pid) == first
    second, chunks = publish()
    assert second != first
    assert any("ALPHA731" in c["text"] and c["source_url"] == doc["source_url"] for c in chunks)
    assert any(c["source_type"] == "confluence" and "7842" in c["text"] for c in chunks)
    assert not client.get("/sources/staging", params={"project_id": pid}).json()["has_changes"]
    receive(2, dict(doc, version=2, content_html="<p>Маркер импорта BETA941.</p>"))
    assert store.active_generation(pid) == second
    _, chunks = publish()
    assert any("BETA941" in c["text"] for c in chunks)
    assert not any("ALPHA731" in c["text"] for c in chunks)
    receive(3, dict(doc, deleted=True, attachments=[]))
    _, chunks = publish()
    assert chunks and all(c["source_type"] != "confluence" for c in chunks)
    assert any("7842" in c["text"] for c in chunks), "manual DOCX survives Confluence removal"


def test_missing_file_is_an_error_but_confirmed_last_source_removal_publishes_empty(monkeypatch, tmp_path):
    from rag_service.sources import confluence as confluence_source
    settings = get_settings()
    pid = "last-source-" + uuid.uuid4().hex[:8]
    for key, value in {"state_dir": str(tmp_path / "state"), "kb_dir": str(tmp_path / "uploads"),
                       "qdrant_collection": pid, "faq_enabled": False,
                       "confluence_sources": json.dumps({"team": {"project_id": pid}})}.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(pipeline, "get_embedder", FakeEmbedder)
    client = TestClient(api.app)
    page = {"document_id": "team:page:1", "page_id": "1", "content_html": "<p>ONLYSOURCE731.</p>"}
    def receive(seq, document):
        confluence_source.receive_batch("team", {"source_id": "team", "batch_id": f"b{seq}",
            "source_sequence": seq, "source_binding": "test", "documents": [document]})
    def publish():
        return client.post("/reindex", json={"project_id": pid, "wait": True, "describe_images": False}).json()
    receive(1, page)
    assert publish()["status"] == "done"
    previous = store.active_generation(pid)
    path = confluence_source.local_files(pid)[0][0]
    path.unlink()
    assert publish()["status"] == "failed"
    assert store.active_generation(pid) == previous
    receive(2, dict(page, deleted=True))
    def no_embeddings():
        raise AssertionError("Removing the last source does not require embeddings")
    monkeypatch.setattr(pipeline, "get_embedder", no_embeddings)
    assert publish()["status"] == "done"
    assert store.active_generation(pid) != previous
    assert store.active_manifest(pid)["counts"]["chunks"] == 0
    assert store.scroll_all(pid, store.active_generation(pid)) == []
