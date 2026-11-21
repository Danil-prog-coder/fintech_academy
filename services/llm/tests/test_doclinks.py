"""FR-GEN-02: signed links from the sources block to a section of an uploaded document."""

from fastapi.testclient import TestClient

import rag_service.api.app as app_mod
from rag_service import doclinks
from rag_service.config import get_settings

DOC = {"doc_id": "bp", "title": "БП Командировка", "file": "bp.pdf", "source_type": "upload"}
CHUNKS = [
    {"doc_id": "bp", "section_number": "1", "section_path": ["1 Содержание"], "chunk_type": "text", "text": "Начало <b>"},
    {"doc_id": "bp", "section_number": "2.4.6", "section_path": ["2 Ошибки", "2.4.6 Исключительная ситуация"],
     "chunk_type": "text", "text": "Требуется обновить страницу."},
    {"doc_id": "other", "section_number": "9", "section_path": ["9 Чужое"], "chunk_type": "text", "text": "секрет"},
]


def _setup(monkeypatch, tmp_path, token="svc"):
    s = get_settings()
    monkeypatch.setattr(s, "auth_disabled", False)
    monkeypatch.setattr(s, "service_api_token", token)
    monkeypatch.setattr(s, "public_base_url", "https://rag.example")
    monkeypatch.setattr(s, "kb_dir", str(tmp_path))
    monkeypatch.setattr(app_mod.store, "active_manifest", lambda pid: {"documents": [DOC]})
    monkeypatch.setattr(app_mod, "get_kb", lambda pid: {"chunks": CHUNKS, "images": {}})
    return s


def test_link_to_section_and_pdf_page(monkeypatch, tmp_path):
    s = _setup(monkeypatch, tmp_path)
    src = {"doc_id": "bp", "section_number": "2.4.6", "section_path": ["2 Ошибки"], "page": 7}
    url = doclinks.source_link(s, "default", src, DOC)
    assert url.startswith("https://rag.example/documents/bp/view?project_id=default&sig=") and url.endswith("#sec-2.4.6")
    (tmp_path / "bp.pdf").write_bytes(b"%PDF-1.4")
    assert doclinks.source_link(s, "default", src, DOC).split("#")[1] == "page=7" and "/file?" in doclinks.source_link(s, "default", src, DOC)
    assert doclinks.source_link(s, "default", {**src, "kind": "tool"}, DOC) is None
    monkeypatch.setattr(s, "doc_links", False)
    assert doclinks.source_link(s, "default", src, DOC) is None


def test_unsigned_link_is_not_built_without_a_key(monkeypatch, tmp_path):
    s = _setup(monkeypatch, tmp_path, token="")
    monkeypatch.setattr(s, "admin_api_token", "")
    assert doclinks.source_link(s, "default", {"doc_id": "bp", "section_number": "1"}, DOC) is None


def test_view_endpoint_requires_signature_or_token(monkeypatch, tmp_path):
    s = _setup(monkeypatch, tmp_path)
    c = TestClient(app_mod.app)
    sig = doclinks.sign(s, "default", "bp")
    r = c.get(f"/documents/bp/view?sig={sig}")
    assert r.status_code == 200 and 'id="sec-2.4.6"' in r.text and "Начало &lt;b&gt;" in r.text and "секрет" not in r.text
    assert c.get("/documents/bp/view?sig=bad").status_code == 401
    assert c.get(f"/documents/other/view?sig={sig}").status_code in (401, 404)  # a signature is per document
    assert c.get("/documents/bp/view", headers={"Authorization": "Bearer svc"}).status_code == 200
    assert c.get(f"/documents/bp/file?sig={sig}").status_code == 404  # no original on disk
    (tmp_path / "bp.pdf").write_bytes(b"%PDF-1.4")
    assert c.get(f"/documents/bp/file?sig={sig}").content.startswith(b"%PDF")
