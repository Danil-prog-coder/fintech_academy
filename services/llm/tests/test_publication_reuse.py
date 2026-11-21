"""Full publication reuses actual local Qdrant vectors, with synthetic content only."""
import base64
import hashlib
import io
import json
import uuid

import pytest
from docx import Document

from rag_service import confluence_source
from rag_service.config import get_settings
from rag_service.index import store
from rag_service.ingest import pipeline
from tests.fakes import FakeEmbedder


@pytest.mark.parametrize("attachment_version", [None, 3])
def test_page_edits_reuse_attachment_and_manual_file(monkeypatch, tmp_path, attachment_version):
    pid = "reuse-" + uuid.uuid4().hex[:8]
    settings = get_settings()
    kb = tmp_path / "uploads"
    kb.mkdir()
    for key, value in {"state_dir": str(tmp_path / "state"), "kb_dir": str(kb),
                       "default_project_id": pid, "qdrant_collection": pid,
                       "confluence_sources": json.dumps({"team": {"project_id": pid}})}.items():
        monkeypatch.setattr(settings, key, value)
    manual = kb / "manual.md"
    manual.write_text("# Manual\n\nMANUAL731", encoding="utf-8")
    document = Document()
    document.add_paragraph("ATTACHMENT941")
    output = io.BytesIO()
    document.save(output)
    data = output.getvalue()
    page = {"document_id": "team:page:1", "page_id": "1", "title": "Guide", "version": 1,
            "source_url": "https://example.test/wiki/pages/1", "content_html": "<p>PAGEALPHA</p>",
            "attachments": [{"attachment_id": "word1", "filename": "guide.docx", "has_data": True,
                             "content_base64": base64.b64encode(data).decode(),
                             "version": attachment_version, "sha256": hashlib.sha256(data).hexdigest()}]}
    parsed, embedded = [], []
    real_parse = pipeline.parse_with_meta

    def parse(path, images, meta):
        parsed.append(meta["path"] if meta else path.name)
        return real_parse(path, images, meta)

    class CountingEmbedder(FakeEmbedder):
        def embed_documents(self, texts):
            embedded.extend(texts)
            return super().embed_documents(texts)

    monkeypatch.setattr(pipeline, "parse_with_meta", parse)
    monkeypatch.setattr(pipeline, "get_embedder", CountingEmbedder)

    def receive(sequence, doc):
        confluence_source.receive_batch("team", {"source_id": "team", "batch_id": str(sequence),
            "source_sequence": sequence, "source_binding": "test", "documents": [doc]})

    def publish():
        return pipeline.ingest([kb], pid, describe=False, include_git=False)

    receive(1, page)
    first = publish()
    assert first["status"] == "ok" and len(parsed) == 3
    parsed.clear()
    embedded.clear()
    unchanged = publish()
    assert unchanged["status"] == "up_to_date"
    assert unchanged["generation"] == first["generation"]
    assert not parsed and not embedded

    receive(2, dict(page, version=2, content_html="<p>PAGEBETA</p>"))
    updated = publish()
    assert updated["status"] == "ok"
    assert parsed == ["Guide.md"]
    assert embedded and all("ATTACHMENT941" not in text and "MANUAL731" not in text for text in embedded)
    assert len(updated["incremental"]["reused_docs"]) == 2
    text = " ".join(p["text"] for p in store.scroll_all(pid, updated["generation"]))
    assert "PAGEBETA" in text and "PAGEALPHA" not in text
    assert "ATTACHMENT941" in text and "MANUAL731" in text

    parsed.clear()
    embedded.clear()
    receive(3, dict(page, deleted=True, attachments=[]))
    removed = publish()
    assert removed["status"] == "ok" and len(removed["incremental"]["removed_docs"]) == 2
    assert not parsed and not embedded
    assert all(p["source_type"] != "confluence" for p in store.scroll_all(pid, removed["generation"]))

    # Chunking configuration changes invalidate reuse even when file bytes are unchanged.
    monkeypatch.setattr(settings, "chunk_target_tokens", settings.chunk_target_tokens + 1)
    assert publish()["status"] == "ok"
    assert parsed == ["manual.md"] and embedded


def test_incomplete_embedding_response_preserves_active_generation(monkeypatch, tmp_path):
    pid = "short-" + uuid.uuid4().hex[:8]
    settings = get_settings()
    for key, value in {"state_dir": str(tmp_path / "state"), "kb_dir": str(tmp_path),
                       "default_project_id": pid, "qdrant_collection": pid, "confluence_sources": ""}.items():
        monkeypatch.setattr(settings, key, value)
    file = tmp_path / "guide.md"
    file.write_text("# Guide\n\nORIGINAL731", encoding="utf-8")
    monkeypatch.setattr(pipeline, "get_embedder", FakeEmbedder)
    initial = pipeline.ingest([file], pid, describe=False, include_git=False)
    assert initial["status"] == "ok"
    file.write_text("# Guide\n\nREPLACEMENT941", encoding="utf-8")

    class ShortEmbedder(FakeEmbedder):
        def embed_documents(self, texts):
            return []

    monkeypatch.setattr(pipeline, "get_embedder", ShortEmbedder)
    failed = pipeline.ingest([file], pid, describe=False, include_git=False)
    assert failed["status"] == "failed"
    assert store.active_generation(pid) == initial["generation"]
