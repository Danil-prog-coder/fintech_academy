"""Question classification, online clusters + background rebuild, hot answers, user_ref (no network)."""

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

import rag_service.analytics.questions as qm
from rag_service import db
from rag_service.analytics.query_logger import QueryLogger, pseudonymize
from rag_service.cache import ExactCache
from rag_service.config import get_settings
from tests.fakes import fake_vec

SRC = ["БП Командировка → 4 Согласование → 4.1"]


def rec(rid, text, action="answer", reason=None, sources=SRC, tier="fast", session="s1", ts=None, **kw):
    return {"request_id": rid, "ts": ts or time.time(), "project_id": "qtest", "session": session, "text": text,
            "action": action, "reason": reason, "sources": sources, "standalone": True, "tier": tier,
            "route": [f"{tier}: simple question"], "confidence_level": "high", **kw}


@pytest.fixture
def qc(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "questions_enabled", True)
    monkeypatch.setattr(s, "question_label_llm", False)
    monkeypatch.setattr(s, "question_assign_threshold", 0.5)
    monkeypatch.setattr(s, "question_cluster_threshold", 0.5)
    monkeypatch.setattr(s, "question_merge_threshold", 0.9)
    monkeypatch.setattr(qm, "_embed", lambda texts: [qm._unit(fake_vec(t)) for t in texts])
    with db.engine().begin() as c:
        c.execute(db.questions.delete().where(db.questions.c.project_id == "qtest"))
        c.execute(db.question_clusters.delete().where(db.question_clusters.c.project_id == "qtest"))
    return qm.QuestionClusters()


def test_classification_fields():
    c = qm.classify(rec("r1", "Кто согласовывает командировку?"))
    assert c["intent"] == "question" and c["on_topic"] and c["answered"] and c["complexity"] == "simple"
    assert c["doc_section"] == "БП Командировка → 4 Согласование" and c["topic"] == "БП Командировка"
    assert qm.classify(rec("r2", "Позовите оператора", action="escalate", reason="user_request", sources=[]))["intent"] == "operator"
    small = qm.classify(rec("r3", "Привет!", reason="no_facts", sources=[]))
    assert small["intent"] == "smalltalk" and not small["on_topic"] and small["topic"] == "Вне тематики"
    off = qm.classify(rec("r4", "Какая погода в Казани?", reason="no_facts", sources=[]))
    assert off["intent"] == "question" and not off["on_topic"] and not off["data"]["unanswered"]
    err = qm.classify(rec("r5", "Не открывается реестр мебели, пишет ошибку", action="offer_operator",
                          reason="agent_decision:no_answer_in_docs", sources=[], tier="heavy"))
    assert err["intent"] == "error" and err["complexity"] == "complex" and err["data"]["unanswered"] and not err["answered"]
    cached = qm.classify(rec("r6", "Кто согласовывает командировку?", cache_hit=True, tier=None))
    assert cached["outcome"] == "cache_answer" and cached["complexity"] is None
    # a follow-up is clustered by the agent's own standalone search query
    fu = rec("r7", "а кто его согласует?", standalone=False, search_queries=["кто согласует командировку"])
    assert qm.classify(fu)["text"] == "кто согласует командировку"


def test_online_assignment_and_stable_rebuild(qc):
    a = ["Кто согласовывает командировку?", "кто согласует командировку руководитель", "согласование командировки кто"]
    b = ["Как списать мебель в реестре мебели?", "списание мебели реестр мебели"]
    for i, t in enumerate(a + b):
        qc.process(rec(f"q{i}", t, session=f"s{i}"))
    assert all(r["cluster_id"] is None for r in qc._rows("qtest", 1))  # no clusters yet → «unclustered»
    rep = qc.rebuild("qtest", 1)
    assert rep["clusters"] == 2 and rep["clustered"] == 5
    ids = {r["request_id"]: r["cluster_id"] for r in qc._rows("qtest", 1)}
    assert ids["q0"] == ids["q1"] == ids["q2"] and ids["q3"] == ids["q4"] and ids["q0"] != ids["q3"]
    # online: a new paraphrase goes to the existing cluster immediately
    new = qc.process(rec("q9", "кто согласовывает командировки", session="s9"))
    assert new["cluster_id"] == ids["q0"] and new["similarity"] >= 0.5
    # off-topic / small talk is not clustered
    assert qc.process(rec("q10", "Привет", reason="no_facts", sources=[]))["cluster_id"] is None
    # rebuild keeps ids
    qc.rebuild("qtest", 1)
    again = {r["request_id"]: r["cluster_id"] for r in qc._rows("qtest", 1)}
    assert again["q0"] == ids["q0"] and again["q3"] == ids["q3"] and again["q9"] == ids["q0"]
    rep = qc.clusters("qtest", 1)
    top = rep["clusters"][0]
    assert top["cluster_id"] == ids["q0"] and top["count"] == 4 and top["people"] == 4 and top["people_unit"] == "session"
    assert top["label"] and top["topic"] == "БП Командировка"


def test_unanswered_clusters_are_doc_gaps(qc):
    for i in range(3):
        qc.process(rec(f"g{i}", f"Как выгрузить отчёт по мебели в excel {i}", action="offer_operator",
                       reason="agent_decision:no_answer_in_docs", sources=[], session=f"g{i}"))
    qc.process(rec("g9", "Кто согласовывает командировку?"))
    qc.rebuild("qtest", 1)
    gaps = qc.unanswered("qtest", 1)
    assert gaps["clusters"] and gaps["clusters"][0]["unanswered"] == 3 and gaps["clusters"][0]["unanswered_people"] == 3
    topics = qc.topics("qtest", 1)
    assert topics["questions"] == 4 and topics["intents"]["question"] == 4


def test_labels_from_cheap_model_only_on_rebuild(qc, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "question_label_llm", True)
    calls = []

    def fake_chat(**kw):
        calls.append(kw["model"])
        return object()

    import rag_service.llm as llm

    monkeypatch.setattr(llm, "chat", fake_chat)
    monkeypatch.setattr(llm, "json_content", lambda r: {"label": "Согласование командировок"})
    for i, t in enumerate(["Кто согласовывает командировку?", "кто согласует командировку руководитель"]):
        qc.process(rec(f"l{i}", t))
    assert calls == []  # online path: no LLM
    qc.rebuild("qtest", 1)
    assert calls and qc.clusters("qtest", 1)["clusters"][0]["label"] == "Согласование командировок"
    n = len(calls)
    qc.rebuild("qtest", 1)
    assert len(calls) == n  # unchanged cluster keeps its label


def test_user_ref_people_and_repeats(qc, monkeypatch):
    s = get_settings()
    assert not qc.remember_user("sess-a", "a" * 32)  # off by default
    monkeypatch.setattr(s, "question_user_ref_enabled", True)
    assert not qc.remember_user("sess-a", "123456789012345678")  # a bare number (Telegram ID) is refused
    ua, ub = "u_" + "a" * 30, "u_" + "b" * 30
    assert qc.remember_user("sess-a", ua) and qc.remember_user("sess-a2", ua) and qc.remember_user("sess-b", ub)
    t0 = time.time() - 3600
    qc.process(rec("p1", "Кто согласовывает командировку?", session=pseudonymize("sess-a"), ts=t0))
    qc.process(rec("p2", "кто согласует командировку руководитель", session=pseudonymize("sess-a2"), ts=t0 + 600))
    qc.process(rec("p3", "согласование командировки кто", session=pseudonymize("sess-b"), ts=t0 + 900))
    qc.rebuild("qtest", 1)
    c = qc.clusters("qtest", 1)["clusters"][0]
    assert c["count"] == 3 and c["people"] == 2 and c["people_unit"] == "user" and c["repeats"] == 1
    assert qm.people_by_request(["p1", "p2"]) == {"p1": ua, "p2": ua}
    assert qc.person("sess-b") == ub and qc.person("sess-x") == pseudonymize("sess-x")


def test_query_logger_feeds_the_worker(qc):
    get_settings().questions_enabled = True
    try:
        QueryLogger().log_turn("qlog", "sess-ql", "qlog1", "Кто согласовывает командировку?",
                               {"action": "answer", "text": "Руководитель [1]", "sources": [{"section_path": SRC[0]}],
                                "confidence_level": "high", "standalone": True, "tier": "fast"})
        qm.get_questions().wait()
        row = qm.get_questions().question("qlog1")
        assert row and row["intent"] == "question" and row["session"] == pseudonymize("sess-ql")
    finally:
        get_settings().questions_enabled = False


def test_hot_answers_people_ttl_and_bound(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "answer_cache_max_entries", 2)
    c = ExactCache()
    c._redis = None
    good = {"action": "answer", "text": "t [1]", "sources": [{"source_id": "S1"}], "confidence_level": "high"}
    for q in ("вопрос один", "вопрос два"):
        c.store("hp", "g1", q, good)
    for who in ("u1", "u1", "u2"):
        assert c.lookup("hp", "g1", "вопрос один", who=who)
    c.lookup("hp", "g1", "вопрос два", who="u3")
    hot = c.hot("hp", "g1")
    assert [(h["question"], h["people"]) for h in hot] == [("вопрос один", 2), ("вопрос два", 1)]
    c.store("hp", "g1", "вопрос три", good)  # over the bound → the coldest entry goes
    assert c.lookup("hp", "g1", "вопрос три") and c.lookup("hp", "g1", "вопрос один")
    assert c.lookup("hp", "g1", "вопрос два") is None
    assert c.hot("hp", "g2") == [] and c.clear("hp") >= 2 and c.hot("hp", "g1") == []


def test_panel_endpoints(qc):
    import rag_service.api.app as app_mod

    qc.process(rec("e1", "Кто согласовывает командировку?"))
    qc.process(rec("e2", "кто согласует командировку руководитель"))
    qc.rebuild("qtest", 1)
    qm._qc = qc
    try:
        cl = TestClient(app_mod.app)
        r = cl.get("/analytics/clusters", params={"project_id": "qtest", "days": 1}).json()
        cid = r["clusters"][0]["cluster_id"]
        assert cl.get(f"/analytics/clusters/{cid}", params={"project_id": "qtest", "days": 1}).json()["questions"]
        assert cl.get("/analytics/top-questions", params={"project_id": "qtest", "days": 1}).json()["top"][0]["count"] == 2
        assert cl.get("/analytics/topics", params={"project_id": "qtest", "days": 1}).json()["questions"] == 2
        assert "clusters" in cl.get("/analytics/unanswered", params={"project_id": "qtest", "days": 1}).json()
        assert cl.get("/analytics/questions/e1").json()["intent"] == "question"
        assert cl.get("/analytics/clusters/nope", params={"project_id": "qtest"}).status_code == 404
        assert cl.post("/analytics/clusters/rebuild", json={"project_id": "qtest", "days": 1}).json()["clusters"] == 1
        assert "exact" in cl.get("/analytics/hot-answers", params={"project_id": "qtest"}).json()
    finally:
        qm._qc = None


def test_calibration_rules():
    """Rules added by the calibration (eval/clustering/report.md)."""
    # a greeting in front of a question is not small talk
    assert qm.classify(rec("c1", "привет, где удаляется сохранённый фильтр?"))["intent"] == "question"
    assert qm.classify(rec("c2", "спасибо, помогло", reason="no_facts", sources=[]))["intent"] == "smalltalk"
    # error codes: embeddings barely separate them, the entity guard does
    assert qm.entity_key("Ошибка BKS-1001 при отправке") == "BKS-1001" and qm.entity_key("выдаёт bks 1002") == "BKS-1002"
    assert qm.entity_key("ошибка 500") == qm.entity_key("Error 500") == "500"
    assert qm.entity_key("сделка 2334-26 не видна") is None and qm.entity_key("суточные 400 рублей") is None
    v = qm._unit(np.ones(8))
    keys = ["BKS-1001", "BKS-1001", "BKS-1002", "BKS-1002", None]
    assert len(qm.QuestionClusters.group([v] * 5, 0.8, 0.86, 2)) == 1
    groups = qm.QuestionClusters.group([v] * 5, 0.8, 0.86, 2, keys=keys)
    assert sorted(len(g) for g in groups) == [2, 3] and all(len({keys[i] for i in g} - {None}) == 1 for g in groups)


def test_stable_ids_are_not_stolen():
    """A bigger new group whose centroid is close to an old cluster must not take the id of the group that continues it."""
    e = np.eye(4, dtype=np.float32)
    old = {"qA": {"centroid": list(e[0])}}
    near_a = qm._unit(e[0] + 0.1 * e[1])
    ids = qm.QuestionClusters.match_ids([[None] * 9 + ["qA"], ["qA", "qA"]], [near_a, qm._unit(e[0])], old, 0.5, 0.9)
    assert ids[1] == ("qA", 1.0) and ids[0][0] is None


def test_online_assignment_respects_codes(qc, monkeypatch):
    monkeypatch.setattr(qm, "_embed", lambda texts: [qm._unit(np.ones(8)) for _ in texts])
    for i, t in enumerate(["Ошибка BKS-1001 при отправке заявки", "выдаёт BKS-1001 при отправке заявки"]):
        qc.process(rec(f"k{i}", t, session=f"s{i}"))
    qc.rebuild("qtest", 1)
    assert qc.process(rec("k8", "Ошибка BKS-1002 при отправке заявки"))["cluster_id"] is None
    assert qc.process(rec("k9", "снова BKS-1001 при отправке заявки"))["cluster_id"] is not None


def test_intent_rules_from_calibration():
    def intent(text):
        return qm.classify({"text": text, "action": "answer", "sources": ["x"], "standalone": True})["intent"]

    assert intent("выскакивает bks-1002 помогите") == "error"
    assert intent("не находит моего руководителя при отправке заявки") == "error"
    assert intent("👍") == "smalltalk"
    assert intent("угу") == "smalltalk"
    assert intent("Позовите кого-нибудь живого") == "operator"
    assert intent("Как подать заявку на отпуск?") == "question"


def test_unsure_on_topic_goes_to_the_llm(qc, monkeypatch):
    """«Unsure» mode: on_topic below QUESTION_MODEL_UNSURE_CONF is flagged, and the async LLM classifier's verdict wins."""
    import sqlalchemy as sa

    from rag_service.analytics import classify as cl

    class Model:
        def __init__(self, p):
            self.p = p

        def predict(self, vec, raw, intent, topics):
            return {"on_topic": ("true", self.p), "topic": ("БП Командировка", 0.9)}

    r = rec("u0", "Какая погода в Казани?")
    c = qm.refine(qm.classify(r), r, np.ones(8), model=Model(0.6), topics=["БП Командировка", "Вне тематики"])
    assert c["on_topic"] and c["data"]["unsure"]
    c = qm.refine(qm.classify(r), r, np.ones(8), model=Model(0.97), topics=["БП Командировка", "Вне тематики"])
    assert not c["data"].get("unsure")
    for rid, t in (("u1", "Какая погода в Казани?"), ("u2", "Кто согласовывает командировку?")):
        qc.process(rec(rid, t, session=rid))
    row = next(x for x in qc._rows("qtest", 1) if x["request_id"] == "u1")
    db.execute(sa.update(db.questions).where(db.questions.c.request_id == "u1").values(data={**row["data"], "unsure": True}))

    class Clf:
        def load(self):
            return {"u1": {"topic": "Вне тематики"}, "u2": {"topic": "Вне тематики"}}

    monkeypatch.setattr(cl, "get_classifier", lambda: Clf())
    assert qc.refresh_topics("qtest", 1) == 1
    got = {x["request_id"]: x for x in qc._rows("qtest", 1)}
    assert not got["u1"]["on_topic"] and got["u1"]["topic"] == "Вне тематики" and got["u1"]["data"]["topic_by"] == "llm_unsure"
    assert got["u2"]["on_topic"]  # the model was sure: the LLM does not override on_topic


def test_second_pass_pairs_mutual_neighbours():
    """QUESTION_PAIR_THRESHOLD: two unclustered questions that are each other's nearest neighbour form a cluster."""
    a, b, c = np.array([1.0, 0, 0]), np.array([0.85, 0.53, 0]), np.array([0, 0, 1.0])
    vs = [qm._unit(v) for v in (a, b, c)]
    assert qm.QuestionClusters.group(vs, 0.9, 0.95, 2) == []
    assert qm.QuestionClusters.group(vs, 0.9, 0.95, 2, pair=0.8) == [[0, 1]]
    assert qm.QuestionClusters.group(vs, 0.9, 0.95, 2, keys=["E-1", "E-2", None], pair=0.8) == []


def test_explicit_urgency_marker_overrides_model():
    """eval/clustering/exp_tone.py: «срочно / горит» → urgent even when the model says normal; off by the setting."""
    from rag_service.config import get_settings

    class Model:
        def predict(self, vec, raw, intent, topics):
            return {"on_topic": ("true", 0.99), "topic": ("БАРС-Офис: фильтры", 0.9), "urgency": ("normal", 0.88), "sentiment": ("neutral", 0.9)}

    r = rec("g1", "нужна инструкция по фильтру в докуменет БО срочно горит")
    c = qm.refine(qm.classify(r), r, np.ones(8), model=Model(), topics=["БАРС-Офис: фильтры", "Вне тематики"])
    assert c["data"]["urgency"] == "urgent" and c["data"]["urgency_by"] == "rule"
    r2 = rec("g2", "как настроить фильтр в БО")
    assert qm.refine(qm.classify(r2), r2, np.ones(8), model=Model(), topics=["БАРС-Офис: фильтры"])["data"]["urgency"] == "normal"
    s = get_settings()
    s.question_urgent_rule = False
    try:
        c = qm.refine(qm.classify(r), r, np.ones(8), model=Model(), topics=["БАРС-Офис: фильтры"])
        assert c["data"]["urgency"] == "normal"
    finally:
        s.question_urgent_rule = True
