"""Answer clusters (analytics/answers.py): features, FAQ candidates, gaps, merge suggestions, consistency (no network)."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

import rag_service.analytics.answers as am
import rag_service.analytics.questions as qm
from rag_service.analytics.store import write_turns
from rag_service.core import db
from rag_service.core.config import get_settings
from tests.fakes import fake_vec
from tests.test_questions import rec

TRIP = ["БП Командировка → 4 Согласование → 4.1 Маршрут"]
FURN = ["Реестр мебели → 3 Списание"]


def test_answer_text_drops_sources_and_markers():
    t = "Согласует **руководитель** [1][2].\n\nИсточники:\n[1] Источник: БП Командировка, раздел 4"
    assert am.answer_text(t) == "Согласует руководитель ."


def test_source_vector_and_outcome_token():
    a = am.source_vector(TRIP)
    b = am.source_vector([{"section_path": TRIP[0], "document_title": "БП Командировка", "chunk_id": "bp:0001"}])
    assert float(a @ b) > 0.6  # same section from the log (path only) and from the API (dict) are close
    assert float(a @ am.source_vector(FURN)) < 0.2
    r1 = am.source_vector([], "answer", "no_facts")
    r2 = am.source_vector([], "answer", "no_facts")
    assert float(r1 @ r2) == pytest.approx(1.0) and float(r1 @ a) < 0.1  # refusals are similar to each other only


def test_combine_is_a_weighted_cosine():
    x, y = np.array([1.0, 0.0]), np.array([0.0, 1.0])
    u, v = am.combine([(x, 0.5), (x, 0.5)]), am.combine([(x, 0.5), (y, 0.5)])
    assert float(u @ v) == pytest.approx(0.5)


def test_source_consistency():
    s1, s2 = frozenset({"s:a"}), frozenset({"s:b"})
    assert am.source_consistency([[s1, s1, s1]]) == 1.0
    assert am.source_consistency([[s1, s2]]) == 0.0
    assert am.source_consistency([[frozenset(), frozenset()]]) is None


@pytest.fixture
def qc(monkeypatch):
    s = get_settings()
    for k, v in {"questions_enabled": True, "question_label_llm": False, "question_assign_threshold": 0.5,
                 "question_cluster_threshold": 0.5, "question_merge_threshold": 0.9, "answer_clusters_enabled": True,
                 "answer_cluster_threshold": 0.5, "question_fallback_embedder": ""}.items():
        monkeypatch.setattr(s, k, v)
    monkeypatch.setattr(qm, "_embed", lambda texts: [qm._unit(fake_vec(t)) for t in texts])
    _clean()
    yield qm.QuestionClusters()
    _clean()  # the turn log is shared with the other tests: rebuild() backfills every logged turn of a project


def _clean():
    with db.engine().begin() as c:
        for t in (db.questions, db.question_clusters, db.turns):
            c.execute(t.delete().where(t.c.project_id == "atest"))


def _log(qc, rid, text, answer, sources, **kw):
    r = {**rec(rid, text, sources=sources, session=rid, answer=answer, **kw), "project_id": "atest"}
    write_turns([r])
    qc.process(r)


def test_faq_candidates_gaps_and_merges(qc):
    ans = "Командировку согласует руководитель подразделения, затем бухгалтерия [1]."
    for i, t in enumerate(["Кто согласовывает командировку?", "кто согласует командировку", "согласование командировки кто",
                           "кто подписывает поездку сотрудника"]):  # the last one: other words, same answer and section
        _log(qc, f"t{i}", t, ans, TRIP)
    for i in range(3):
        _log(qc, f"g{i}", f"Как выгрузить реестр мебели в excel {i}", "В базе знаний нет ответа на этот вопрос.", [],
             action="offer_operator", reason="agent_decision:no_answer_in_docs")
    qc.rebuild("atest", 1)
    out = am.build("atest", 1)
    assert out["enabled"] and out["questions"] == 7
    faq = out["faq_candidates"]
    assert faq and faq[0]["count"] == 4 and faq[0]["source_consistency"] == 1.0 and faq[0]["answered_share"] == 1.0
    assert faq[0]["sections"] == [TRIP[0]]
    gap = out["gaps"]
    assert gap and gap[0]["count"] == 3 and gap[0]["unanswered"] == 3 and not gap[0]["faq_candidate"]
    assert out["answer_consistency"]["overall"] == 1.0
    # «кто подписывает поездку» (other words) is mapped onto the same answer cluster as the paraphrases
    assert "t3" in faq[0]["request_ids"]
    qcl = {r["request_id"]: r["cluster_id"] for r in qc._rows("atest", 1)}
    if qcl["t3"] != qcl["t0"]:  # not in their question cluster → the answer cluster suggests merging it in
        assert any(qcl["t0"] in m["question_clusters"] for m in out["merge_suggestions"]) or qcl["t3"] is None


def test_disabled_flag_keeps_the_contract(qc, monkeypatch):
    import rag_service.analytics.digest as dg

    monkeypatch.setattr(get_settings(), "answer_clusters_enabled", False)
    assert am.build("atest", 1) == {"enabled": False, "project_id": "atest"}
    _log(qc, "x1", "Кто согласовывает командировку?", "Руководитель [1].", TRIP)
    assert "answer_clusters" not in dg.daily_digest("atest")
    monkeypatch.setattr(get_settings(), "answer_clusters_enabled", True)
    d = dg.daily_digest("atest")
    assert "answer_clusters" in d and d["answer_clusters"]["questions"] >= 1


def test_endpoint(qc, monkeypatch):
    from rag_service.api.app import app

    monkeypatch.setattr(get_settings(), "auth_disabled", True, raising=False)
    _log(qc, "e1", "Кто согласовывает командировку?", "Руководитель [1].", TRIP)
    with TestClient(app) as c:
        r = c.get("/analytics/answer-clusters", params={"project_id": "atest", "days": 1},
                  headers={"Authorization": f"Bearer {get_settings().admin_api_token or 'x'}"})
    assert r.status_code == 200 and r.json()["enabled"] is True
