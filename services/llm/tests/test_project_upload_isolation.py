import io
import uuid

from docx import Document
from fastapi.testclient import TestClient
from PIL import Image

import rag_service.api.app as api
from rag_service.core.config import get_settings
from rag_service.core.project_paths import upload_dir
from rag_service.index import store
from rag_service.ingest import pipeline
from tests.fakes import FakeEmbedder


def word(text, color):
    document = Document()
    document.add_paragraph(text)
    image = io.BytesIO()
    Image.new("RGB", (30, 30), color).save(image, format="PNG")
    image.seek(0)
    document.add_picture(image)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def test_project_uploads_images_and_published_originals_are_isolated(monkeypatch, tmp_path):
    settings = get_settings()
    for key, value in {"kb_dir": str(tmp_path / "uploads"), "state_dir": str(tmp_path / "state"),
                       "default_project_id": "legacy", "confluence_sources": "", "faq_enabled": False,
                       "qdrant_collection": "isolated-" + uuid.uuid4().hex[:8]}.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(pipeline, "get_embedder", FakeEmbedder)
    client = TestClient(api.app)
    a, b = word("PROJECTALPHA SECRET731", "red"), word("PROJECTBETA SECRET941", "blue")
    for pid, data in (("alpha", a), ("beta", b)):
        response = client.post("/documents", data={"project_id": pid},
                               files={"files": ("same.docx", data, "application/octet-stream")})
        assert response.status_code == 200
        job = client.post("/reindex", json={"project_id": pid, "wait": True, "describe_images": False}).json()
        assert job["status"] == "done", job
    assert (upload_dir(settings, "alpha") / "general" / "same.docx").read_bytes() == a
    assert (upload_dir(settings, "beta") / "general" / "same.docx").read_bytes() == b
    manifests = [store.active_manifest(p) for p in ("alpha", "beta")]
    image_paths = [{i["path"] for i in m["images"].values()} for m in manifests]
    assert image_paths[0] and image_paths[1] and image_paths[0].isdisjoint(image_paths[1])
    for pid, wanted, forbidden in (("alpha", "SECRET731", "SECRET941"), ("beta", "SECRET941", "SECRET731")):
        text = " ".join(c["text"] for c in store.scroll_all(pid, store.active_generation(pid)))
        assert wanted in text and forbidden not in text
    old_generation = store.active_generation("alpha")
    replacement = word("NEWALPHA CONTENT551", "green")
    client.post("/documents", data={"project_id": "alpha"},
                files={"files": ("same.docx", replacement, "application/octet-stream")})
    original = client.get("/documents/same/file", params={"project_id": "alpha"})
    assert original.status_code == 200 and original.content == a
    client.post("/documents", data={"project_id": "alpha"},
                files={"files": ("broken.docx", b"broken", "application/octet-stream")})
    failed = client.post("/reindex", json={"project_id": "alpha", "wait": True, "describe_images": False}).json()
    assert failed["status"] == "failed"
    assert store.active_generation("alpha") == old_generation
    assert client.get("/documents/same/file", params={"project_id": "alpha"}).content == a
