"""Trends / spikes, topic hierarchy, 2-D map (analytics/insights.py) and the trained classifier (analytics/qmodel.py)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from fastapi.testclient import TestClient

import rag_service.analytics.insights as ins
import rag_service.analytics.questions as qm
from rag_service.analytics import qmodel
from tests.test_digest import qc  # noqa: F401  (fixture)
from tests.test_questions import rec

MSK = ZoneInfo("Europe/Moscow")


def at(day: int, h: int = 12) -> float:
    return datetime(2026, 11, day, h, 0, tzinfo=MSK).timestamp()


def test_spike_and_trend_detection():
    flat = [1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 9, 1, 0, 1]
    sp = ins.spikes(flat, z_thr=3, min_count=4)
    assert [x["day"] for x in sp] == [10] and sp[0]["count"] == 9
    assert ins.spikes([2] * 14, 3, 4) == []
    assert ins.trend([0] * 7 + [3, 4, 5, 4, 6, 5, 7])["status"] == "new"
    assert ins.trend([1] * 7 + [3, 4, 5, 4, 6, 5, 7])["status"] == "rising"
    assert ins.trend([6, 5, 7, 6, 5, 6, 7] + [0, 1, 0, 0, 1, 0, 0])["status"] == "falling"
    assert ins.trend([2] * 14)["status"] == "stable"
    young = [0] * 13 + [9]  # the log started today: no spike, no trend yet
    assert ins.spikes(young, 3, 4, start=13) == [] and ins.trend(young, start=13)["status"] == "insufficient_history"
    xy, _, _ = ins.pca2(np.random.default_rng(0).normal(size=(20, 8)))
    assert xy.shape == (20, 2)


def test_trends_tree_and_map(qc):  # noqa: F811
    for d in range(1, 15):
        qc.process(rec(f"m{d}", "Как списать мебель в реестре мебели?", session=f"s{d}", ts=at(d)))
    for i in range(6):  # a burst on Nov 12
        qc.process(rec(f"t{i}", "кто согласовывает командировку руководитель", session=f"b{i}", ts=at(12, 10 + i)))
    qc.process(rec("t9", "Кто согласовывает командировку?", ts=at(3)))
    qc.process(rec("p0", "Привет!", reason="no_facts", sources=[], ts=at(5)))
    qc.rebuild("qtest", 3650)
    tr = ins.trends("qtest", days=14, tz="Europe/Moscow", end="2026-11-14")
    assert tr["days"][0] == "2026-11-01" and len(tr["total"]["series"]) == 14
    trip = next(t for t in tr["topics"] if t["topic"] == "БП Командировка")
    assert trip["series"][11] == 6 and [s["date"] for s in trip["spikes"]] == ["2026-11-12"]
    assert any(s["date"] == "2026-11-12" for s in tr["spikes"])
    tree = ins.topic_tree("qtest", days=3650)
    topics = {t["topic"]: t for t in tree["topics"]}
    assert topics["БП Командировка"]["count"] == 7 and topics["БП Командировка"]["clusters"]
    sub = topics["БП Командировка"]["clusters"][0]
    assert sub["count"] >= 6 and sub["examples"] and tree["off_topic"]["count"] == 1
    mp = ins.cluster_map("qtest", days=3650)
    assert mp["method"] == "pca" and len(mp["points"]) == 21 and mp["clusters"]
    assert all(-1.0001 <= p["x"] <= 1.0001 for p in mp["points"])
    from rag_service.api.app import app

    with TestClient(app) as c:
        assert c.get("/analytics/trends", params={"project_id": "qtest", "date": "2026-11-14"}).status_code == 200
        assert c.get("/analytics/trends", params={"date": "bad"}).status_code == 422
        assert c.get("/analytics/topics/tree", params={"project_id": "qtest", "days": 3650}).json()["topics"]
        assert c.get("/analytics/clusters/map", params={"project_id": "qtest", "days": 3650}).json()["points"]


def test_trained_model_refines_rules(tmp_path):
    rng = np.random.default_rng(1)
    dim = 16
    centers = {"question": rng.normal(size=dim), "error": rng.normal(size=dim)}
    X, y = [], []
    for lab, c in centers.items():
        for _ in range(40):
            v = c + 0.3 * rng.normal(size=dim)
            X.append(qmodel.features(v, "текст", "question"))
            y.append(lab)
    X = np.stack(X)
    head = qmodel.train_head(X, y)
    labs, p = qmodel.predict_head(head, X)
    assert np.mean([a == b for a, b in zip(labs, y)]) > 0.95 and p.min() > 0.3
    path = tmp_path / "m.npz"
    qmodel.save({"intent": head, "sentiment": qmodel.train_head(X, ["negative" if i % 2 else "neutral" for i in range(len(y))])},
                {"dim": dim}, path)
    m = qmodel.QuestionModel(path)
    assert m.ready(dim) and not m.ready(dim + 1)
    c = qm.classify(rec("r1", "Как подать заявку?"))
    assert c["intent"] == "question" and c["data"]["intent_by"] == "rules"
    qm.refine(c, rec("r1", "Как подать заявку?"), centers["error"], model=m, topics=[])
    assert c["intent"] == "error" and c["data"]["intent_by"] == "model" and c["data"]["model"]["intent"][0] == "error"
    assert c["data"]["sentiment"] in ("negative", "neutral")
    # an explicit operator request is never overridden
    c = qm.classify(rec("r2", "Позовите оператора", action="escalate", reason="user_request", sources=[]))
    qm.refine(c, rec("r2", "Позовите оператора", action="escalate", reason="user_request", sources=[]), centers["error"], model=m, topics=[])
    assert c["intent"] == "operator"
    # another embedder (dimension) → rules untouched
    c = qm.classify(rec("r3", "Как подать заявку?"))
    qm.refine(c, rec("r3", "Как подать заявку?"), np.ones(dim + 3), model=m, topics=[])
    assert c["intent"] == "question" and "model" not in c["data"]


def test_question_saved_when_embedding_fails(qc, monkeypatch):  # noqa: F811
    def boom(texts):
        raise RuntimeError("429 quota")

    monkeypatch.setattr(qm, "_embed", boom)
    c = qc.process(rec("e1", "Как списать мебель в реестре мебели?"))
    assert c["cluster_id"] is None and qc.question("e1")["intent"] == "question"


def test_reports_are_consistent(qc):  # noqa: F811
    """Slope does not depend on the requested length; no z for a young log; «Вне тематики» == off_topic;
    a cluster's 7-day trend never exceeds its count in the tree; subject spellings are merged."""
    s = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
    assert ins.trend([0] * 16 + s)["slope_per_day"] == ins.trend(s)["slope_per_day"] == 1.0
    assert ins.trend([0] * 13 + [9], start=13)["z"] is None
    assert ins.topic_of({"on_topic": False, "topic": "БП Командировка"}) == "Вне тематики"
    assert ins.topic_of({"on_topic": True, "topic": "Вне тематики"}) == "Без темы"
    from rag_service.analytics.digest import daily_digest, merge_subjects

    assert merge_subjects(["командировка", "БП Командировка", "бизнес-процесс Командировка", "Командировки"]) == {"командировка": 4}
    for d in range(1, 15):
        qc.process(rec(f"c{d}", "Как списать мебель в реестре мебели?", session=f"s{d}", ts=at(d)))
    qc.process(rec("o1", "Привет!", reason="no_facts", sources=[], ts=at(14)))
    qc.rebuild("qtest", 3650)
    tree = ins.topic_tree("qtest", days=30)
    for t in tree["topics"]:
        assert t["topic"] != "Вне тематики"
        for c in t["clusters"]:
            assert c["trend"] is None or c["trend"]["last"] <= c["count"]
    dg = daily_digest("qtest", day="2026-11-14", tz="Europe/Moscow")
    off = next((t["count"] for t in dg["topics"] if t["topic"] == "Вне тематики"), 0)
    assert off == dg["off_topic"]


def test_fallback_embedder_and_per_model_thresholds(qc, monkeypatch):  # noqa: F811
    """Main embedder down → analytics uses the local one (faked here) with its own thresholds; centroids of another
    embedder are never compared; the rebuild reports the change of embedder."""
    from rag_service.analytics import embedder as emb
    from rag_service.config import get_settings
    from tests.test_questions import fake_vec

    s = get_settings()
    assert emb.model_key("google/gemini-embedding-001") == "gemini-embedding-001" and emb.thresholds("BAAI/bge-m3")["cluster"] == 0.74
    assert emb.thresholds()["cluster"] == s.question_cluster_threshold  # the main model keeps the QUESTION_* settings
    for d in range(1, 5):
        qc.process(rec(f"g{d}", "Как списать мебель в реестре мебели?", session=f"s{d}", ts=at(d)))
    assert qc.rebuild("qtest", 3650)["embedding_model"] == emb.main_model()

    def boom(texts):
        raise RuntimeError("429 quota")

    monkeypatch.setattr(qm, "_embed", boom)
    monkeypatch.setattr(s, "question_fallback_embedder", "BAAI/bge-m3")
    monkeypatch.setattr(emb, "_down_until", 0.0)
    monkeypatch.setattr(emb, "local_embed", lambda texts: [qm._unit(fake_vec(t + " ")) for t in texts])
    c = qc.process(rec("f1", "Как списать мебель в реестре мебели?", ts=at(5)))
    assert c["data"]["embed_model"] == "bge-m3" and c["cluster_id"] is None  # gemini centroids are not comparable
    assert qc.question("f1")["intent"] == "question" and emb.status()["fallback_active"]
    r = qc.rebuild("qtest", 3650)
    assert r["embedding_model"] == "bge-m3" and r["model_changed"] == [emb.main_model(), "bge-m3"] and r["thresholds"]["cluster"] == 0.74


def test_slow_main_embedder_trips_the_breaker(monkeypatch):
    """A main embedder stuck in 429 retries does not hold analytics: after QUESTION_EMBED_TIMEOUT_S the fallback answers."""
    import time as _t

    from rag_service.analytics import embedder as emb
    from rag_service.config import get_settings
    from tests.test_questions import fake_vec

    s = get_settings()
    monkeypatch.setattr(s, "question_fallback_embedder", "BAAI/bge-m3")
    monkeypatch.setattr(s, "question_embed_timeout_s", 0.2)
    monkeypatch.setattr(emb, "_down_until", 0.0)
    monkeypatch.setattr(qm, "_embed", lambda texts: _t.sleep(2) or [qm._unit(fake_vec(t)) for t in texts])
    monkeypatch.setattr(emb, "local_embed", lambda texts: [qm._unit(fake_vec(t + " ")) for t in texts])
    t0 = _t.time()
    _, model = emb.embed(["как списать мебель"])
    assert model == "bge-m3" and _t.time() - t0 < 1.5
    t0 = _t.time()
    assert emb.embed(["ещё вопрос"])[1] == "bge-m3" and _t.time() - t0 < 0.5  # breaker open: no new wait
