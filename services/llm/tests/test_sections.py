"""Sections of a project's knowledge base and per-request section restriction (admin service → allowed_sections)."""
import uuid

import pytest
from fastapi.testclient import TestClient

import rag_service.api.app as api
from rag_service.core.config import get_settings
from rag_service.core.project_paths import upload_dir
from rag_service.index import store
from rag_service.ingest import pipeline
from rag_service.retrieval import access, search
from rag_service.retrieval.kb import get_kb
from tests.fakes import FakeEmbedder

PID = "sections-p1"


@pytest.fixture
def client(monkeypatch, tmp_path):
    settings = get_settings()
    for key, value in {"kb_dir": str(tmp_path / "uploads"), "state_dir": str(tmp_path / "state"),
                       "confluence_sources": "", "faq_enabled": False, "rerank_mode": "none",
                       "qdrant_collection": "sections-" + uuid.uuid4().hex[:8]}.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(pipeline, "get_embedder", FakeEmbedder)
    monkeypatch.setattr(search, "get_embedder", FakeEmbedder)
    c = TestClient(api.app)
    for section, name, text in (("general", "vacation.md", "# Отпуск\n\nОтпуск оформляется через портал ОТПУСКПОРТАЛ."),
                                ("security", "keys.md", "# Ключи\n\nКлюч доступа к серверу хранится в СЕЙФЗОНА.")):
        r = c.post("/documents", data={"project_id": PID, "section": section},
                   files={"files": (name, text.encode(), "text/markdown")})
        assert r.status_code == 200, r.text
    job = c.post("/reindex", json={"project_id": PID, "wait": True, "describe_images": False}).json()
    assert job["status"] == "done", job
    return c


def _texts(results):
    return " ".join(r["text"] for r in results)


def test_documents_carry_their_section(client):
    docs = {d["doc_id"]: d["section"] for d in client.get("/documents", params={"project_id": PID}).json()["documents"]}
    assert docs == {"vacation": "general", "keys": "security"}
    staged = client.get("/documents/staged", params={"project_id": PID}).json()["files"]
    assert {(f["name"], f["section"]) for f in staged} == {("vacation.md", "general"), ("keys.md", "security")}


def test_restriction_hides_other_sections_from_search_and_kb(client):
    open_all = search.search(PID, "СЕЙФЗОНА ключ доступа", rerank=False)
    assert "СЕЙФЗОНА" in _texts(open_all["results"])
    with access.restrict_sections(PID, ["general"]):
        hidden = search.search(PID, "СЕЙФЗОНА ключ доступа", rerank=False)
        assert "СЕЙФЗОНА" not in _texts(hidden["results"])
        assert set(get_kb(PID)["docs"]) == {"vacation"}
    # the restriction ends with the block: the cached project view is untouched
    assert set(get_kb(PID)["docs"]) == {"vacation", "keys"}


def test_empty_allowed_list_hides_everything_none_hides_nothing(client):
    assert access.denied_for_sections(PID, None) == frozenset()
    assert access.denied_for_sections(PID, []) == {"vacation", "keys"}


def test_restricted_answers_are_not_served_from_cache(client):
    answer = {"sources": [{"doc_id": "keys", "chunk_id": "keys:0000"}], "image_ids": []}
    with access.restrict_sections(PID, ["general"]):
        assert not access.answer_allowed(PID, answer)
    assert access.answer_allowed(PID, answer)


def test_same_name_in_another_section_is_a_conflict(client):
    r = client.post("/documents", data={"project_id": PID, "section": "security"},
                    files={"files": ("vacation.md", b"# x\n\ny", "text/markdown")})
    assert r.status_code == 409


def test_bad_section_name_is_rejected(client):
    r = client.post("/documents", data={"project_id": PID, "section": "../etc"},
                    files={"files": ("a.md", b"# x\n\ny", "text/markdown")})
    assert r.status_code == 422


def test_replace_touches_only_its_section(client):
    r = client.post("/documents", data={"project_id": PID, "section": "general", "mode": "replace"},
                    files={"files": ("holidays.md", "# Праздники\n\nПраздничный график.".encode(), "text/markdown")})
    assert r.status_code == 200
    root = upload_dir(get_settings(), PID)
    assert not (root / "general" / "vacation.md").exists()
    assert (root / "general" / "holidays.md").exists() and (root / "security" / "keys.md").exists()


def test_delete_document_republishes_without_it(client):
    r = client.delete("/documents/keys", params={"project_id": PID, "wait": True})
    assert r.status_code == 200 and r.json()["job"]["status"] == "done"
    docs = {d["doc_id"] for d in client.get("/documents", params={"project_id": PID}).json()["documents"]}
    assert docs == {"vacation"}
    assert client.delete("/documents/keys", params={"project_id": PID}).status_code == 404


def test_rollback_keeps_state_file_consistent(client):
    client.delete("/documents/keys", params={"project_id": PID, "wait": True})
    before = store.active_generation(PID)
    assert client.post("/rollback", params={"project_id": PID}).status_code == 200
    after = store.active_generation(PID)
    assert after != before
    assert {d["doc_id"] for d in store.active_manifest(PID)["documents"]} == {"vacation", "keys"}


def test_support_answer_lands_in_the_project_and_is_indexed(client):
    r = client.post("/knowledge", json={"project_id": PID, "question": "Где взять пропуск на парковку?",
                                        "answer": "Пропуск ПАРКОВКА77 выдаёт охрана на первом этаже.", "wait": True})
    assert r.status_code == 200, r.text
    assert r.json()["section"] == "support-answers" and r.json()["job"]["status"] == "done"
    docs = client.get("/documents", params={"project_id": PID}).json()["documents"]
    assert any(d["section"] == "support-answers" for d in docs)
    assert "ПАРКОВКА77" in _texts(search.search(PID, "пропуск на парковку ПАРКОВКА77", rerank=False)["results"])
