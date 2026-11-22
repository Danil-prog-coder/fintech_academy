"""Semantic FAQ cache (FR-FAQ-01..06, 08) with fake embeddings and local Qdrant (no network)."""

import time

import pytest

import rag_service.faq.service as svc
from rag_service.core.config import get_settings
from rag_service.faq.entities import extract_entities, same_entities, title_vocabulary
from tests.fakes import FakeEmbedder

TITLES = ["БП Командировка", "Реестр мебели", "Функциональные возможности работы с БАРС-Офисом"]
SRC = [{"source_id": "S1", "chunk_id": "bp:0003", "document_title": "БП Командировка", "section_path": "БП Командировка → 4 Согласование",
        "excerpt": "согласует руководитель", "chunk_type": "text", "image_ids": []}]


@pytest.fixture
def faq(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "state_dir", str(tmp_path))
    monkeypatch.setattr(s, "faq_collection", f"faq_test_{int(time.time() * 1e6)}")
    monkeypatch.setattr(s, "faq_match_threshold", 0.5)
    monkeypatch.setattr(s, "faq_cluster_threshold", 0.6)
    monkeypatch.setattr(svc, "get_embedder", lambda: FakeEmbedder())
    state = {"gen": "g1", "docs": [{"doc_id": "bp", "title": TITLES[0], "content_hash": "h1"},
                                    {"doc_id": "mebel", "title": TITLES[1], "content_hash": "m1"}]}
    monkeypatch.setattr(svc.store, "active_generation", lambda pid: state["gen"])
    monkeypatch.setattr(svc.store, "active_manifest", lambda pid: {"documents": state["docs"]})
    f = svc.FaqService()
    f._state = state
    return f


def test_entities_separate_registries():
    v = title_vocabulary(TITLES)
    a = extract_entities("Какие статусы в реестре мебели?", v)
    b = extract_entities("Какие статусы в реестре техники?", v)
    assert not same_entities(a, b)
    assert same_entities(extract_entities("Кто согласовывает БП Командировки?", v), extract_entities("кто согласует командировку", v))
    assert extract_entities("фильтр !> 200", v)["operators"] == ["!>"]


def test_manual_entry_hit_paraphrase_and_no_false_hit(faq):
    e = faq.create_manual("default", "Какие статусы в реестре мебели?", "Статусы: в эксплуатации, списано [1]",
                          sources=[dict(SRC[0], chunk_id="mebel:0002", document_title="Реестр мебели")])["entry"]
    assert e["origin"] == "manual" and e["enabled"]
    hit = faq.lookup("default", "g1", "какие статусы бывают в реестре мебели")
    assert hit and hit["entry"]["id"] == e["id"]
    # FR-FAQ-04 KP: similar question about another registry is NOT served from the cache
    assert faq.lookup("default", "g1", "Какие статусы в реестре техники?") is None
    # other generation → miss (key = project_id + generation)
    assert faq.lookup("default", "g2", "какие статусы бывают в реестре мебели") is None


def test_llm_equivalence_rejects(faq, monkeypatch):
    monkeypatch.setattr(get_settings(), "faq_verify_llm", True)
    faq.create_manual("default", "Кто согласовывает БП Командировки?", "Руководитель [1]", sources=SRC)
    monkeypatch.setattr(faq, "_equivalent_llm", lambda a, b: False)
    assert faq.lookup("default", "g1", "кто согласует командировку сотрудника") is None
    faq._eq_cache.clear()
    monkeypatch.setattr(faq, "_equivalent_llm", lambda a, b: True)
    assert faq.lookup("default", "g1", "кто согласует командировку сотрудника") is not None


def test_delete_no_cache_stoplist_and_history_restore(faq):
    e = faq.create_manual("default", "Кто согласовывает БП Командировки?", "Руководитель [1]", sources=SRC)["entry"]
    faq.edit("default", e["id"], text="Руководитель отдела [1]", by="admin")
    snaps = [h for h in faq.history("default", e["id"]) if h.get("before")]
    assert snaps and snaps[0]["before"]["answer"]["text"] == "Руководитель [1]"
    restored = faq.restore("default", e["id"], 0)
    assert restored["answer"]["text"] == "Руководитель [1]"
    assert faq.delete("default", e["id"], no_cache=True)
    st = faq.load("default")
    assert st["stoplist"] and st["stoplist"][0]["question"].startswith("Кто согласовывает")
    assert faq.lookup("default", "g1", "Кто согласовывает БП Командировки?") is None
    assert faq.unstop("default", st["stoplist"][0]["id"])


def test_generation_change_manual_needs_review_auto_carried(faq):
    m = faq.create_manual("default", "Кто согласовывает БП Командировки?", "Руководитель [1]", sources=SRC)["entry"]
    a = faq._new_entry("default", "Какие кнопки в реестре мебели?", {"action": "answer", "text": "t [1]",
                       "sources": [dict(SRC[0], chunk_id="mebel:0001")], "confidence_level": "high"}, "auto")
    st = faq.load("default")
    st["entries"][a["id"]] = a
    faq.save("default", st)
    faq._index_entry("default", a)
    # new KB version: «БП Командировка» changed, «Реестр мебели» did not
    faq._state["gen"] = "g2"
    faq._state["docs"][0]["content_hash"] = "h2"
    rep = faq.on_generation_change("default", rebuild=False)
    assert m["id"] in rep["manual_review"] and a["id"] in rep["carried"]
    st = faq.load("default")
    assert not st["entries"][m["id"]]["enabled"] and "sources_changed" in st["entries"][m["id"]]["flags"]
    assert faq.lookup("default", "g2", "какие кнопки в реестре мебели") is not None


def test_dislikes_disable_entry(faq):
    e = faq.create_manual("default", "Кто согласовывает БП Командировки?", "Руководитель [1]", sources=SRC)["entry"]
    for _ in range(get_settings().faq_dislike_threshold):
        faq.feedback("default", e["id"], "down")
    assert not faq.get_entry("default", e["id"])["enabled"]
    assert faq.lookup("default", "g1", "Кто согласовывает БП Командировки?") is None


def test_ttl_expired_auto_not_served(faq):
    a = faq._new_entry("default", "Какие кнопки в реестре мебели?", {"action": "answer", "text": "t", "sources": SRC,
                       "confidence_level": "high"}, "auto")
    a["expires_at"] = time.time() - 1
    st = faq.load("default")
    st["entries"][a["id"]] = a
    faq.save("default", st)
    faq._index_entry("default", a)
    assert faq.lookup("default", "g1", "Какие кнопки в реестре мебели?") is None


def _turn(text, ts, rid, action="answer", standalone=True, sources=None):
    return {"ts": ts, "request_id": rid, "text": text, "action": action, "standalone": standalone,
            "sources": sources or ["БП Командировка → 4 Согласование"], "session": rid}


def test_recompute_clusters_topk_and_builds(faq, monkeypatch):
    now = time.time()
    recs = [_turn("Кто согласовывает БП Командировки?", now - 100, "r1"),
            _turn("кто согласовывает бп командировки", now - 90, "r2"),
            _turn("Кто согласовывает командировки в БП?", now - 80, "r3"),
            _turn("Какие статусы в реестре мебели?", now - 70, "r4"),
            _turn("Какие статусы в реестре техники?", now - 60, "r5", action="offer_operator"),
            _turn("Какие статусы в реестре техники?", now - 50, "r6", action="offer_operator"),
            _turn("Позовите оператора", now - 40, "r7", action="escalate"),
            dict(_turn("Какая сегодня погода в Казани?", now - 30, "r8"), sources=[]),
            dict(_turn("Какая сегодня погода в Казани?", now - 20, "r9"), sources=[])]
    import rag_service.analytics.store as an_store

    monkeypatch.setattr(an_store, "load_turns", lambda days, pid=None, **k: recs)
    monkeypatch.setattr(an_store, "load_feedback", lambda: {"r6": "down"})
    built = []

    def fake_build(pid, q):
        built.append(q)
        if "техники" in q:
            return None, "action=offer_operator"
        return {"action": "answer", "text": "Руководитель [1]", "sources": SRC, "confidence_level": "high", "image_ids": []}, "ok"

    monkeypatch.setattr(faq, "build_answer", fake_build)
    rep = faq.recompute("default", build=True)
    st = faq.stats("default")
    top = {c["canonical"]: c for c in st["top"]}
    # FR-FAQ-01: paraphrases share a cluster; «мебели» and «техники» never do; operator requests are skipped
    assert any(c["count"] == 3 for c in st["top"])
    assert all("оператора" not in c["canonical"] and "погода" not in c["canonical"] for c in st["top"])
    tech = [c for k, c in top.items() if "техники" in k]
    assert tech and tech[0]["needs_docs"] and tech[0]["dislikes"] == 1
    assert len(rep["built"]) == 1 and rep["build_failed"]
    # FR-FAQ-02: documentation places
    assert top[next(k for k in top if "согласовывает" in k.lower())]["doc_places"][0][0].startswith("БП Командировка")
    # the built answer is served for a paraphrase
    assert faq.lookup("default", "g1", "кто согласовывает командировки")
