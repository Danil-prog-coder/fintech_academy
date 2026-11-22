"""Daily digest of classified questions (analytics/digest.py): calendar day in a time zone, counts, clusters, gaps."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import rag_service.analytics.digest as dg
import rag_service.analytics.questions as qm
from rag_service.core import db
from rag_service.core.config import get_settings
from tests.fakes import fake_vec
from tests.test_questions import rec

MSK = ZoneInfo("Europe/Moscow")


def at(h: int, day: int = 10) -> float:
    return datetime(2026, 11, day, h, 0, tzinfo=MSK).timestamp()


@pytest.fixture
def qc(monkeypatch):
    s = get_settings()
    for k, v in {"questions_enabled": True, "question_label_llm": False, "question_assign_threshold": 0.5,
                 "question_cluster_threshold": 0.5, "question_merge_threshold": 0.9, "question_cluster_days": 3650}.items():
        monkeypatch.setattr(s, k, v)
    monkeypatch.setattr(qm, "_embed", lambda texts: [qm._unit(fake_vec(t)) for t in texts])
    with db.engine().begin() as c:
        c.execute(db.questions.delete().where(db.questions.c.project_id == "qtest"))
        c.execute(db.question_clusters.delete().where(db.question_clusters.c.project_id == "qtest"))
    return qm.QuestionClusters()


def test_daily_digest_counts_and_clusters(qc):
    trip = ["Кто согласовывает командировку?", "кто согласует командировку руководитель", "согласование командировки кто"]
    for i, t in enumerate(trip):
        qc.process(rec(f"d{i}", t, session=f"s{i % 2}", ts=at(10 + i)))
    for i, t in enumerate(["Как списать мебель в реестре мебели?", "списание мебели реестр мебели"]):
        qc.process(rec(f"g{i}", t, action="offer_operator", reason="agent_decision:no_answer_in_docs", sources=[],
                       tier="heavy", session=f"s{5 + i}", ts=at(12 + i)))
    qc.process(rec("p0", "Привет!", reason="no_facts", sources=[], ts=at(9)))
    qc.process(rec("x0", "Позовите оператора", action="escalate", reason="user_request", sources=[], ts=at(15)))
    qc.process(rec("late", "Кто согласовывает командировку?", ts=at(0, day=11) + 60))  # next day in Moscow
    qc.process(rec("early", "Кто согласовывает командировку?", ts=at(23, day=9)))  # previous day
    qc.rebuild("qtest", 3650)
    d = dg.daily_digest("qtest", "2026-11-10", "Europe/Moscow")
    assert d["date"] == "2026-11-10" and d["tz"] == "Europe/Moscow" and d["complete"]
    assert d["questions"] == 7 and d["intents"] == {"question": 5, "smalltalk": 1, "operator": 1}
    # «позовите оператора» is not on-topic (golden-set convention), only small talk and it are off-topic here
    assert d["on_topic"] == 5 and d["off_topic"] == 2 and d["answered"] == 3 and d["unanswered"] == 2
    assert d["complexity"] == {"simple": 3, "complex": 2}  # on-topic questions only
    assert {t["topic"] for t in d["topics"]} >= {"БП Командировка", "Реестр мебели", "Вне тематики"}
    top = d["top_clusters"][0]
    assert top["count"] == 3 and top["people"] == 2 and top["answered"] == 3 and len(top["request_ids"]) == 3
    assert top["trend"] == pytest.approx(3 / (1 / 7), rel=0.01)  # one question in the previous 7 days
    gaps = d["unanswered_clusters"]
    assert len(gaps) == 1 and gaps[0]["unanswered"] == 2 and gaps[0]["unanswered_people"] == 2 and gaps[0]["examples"]
    assert len(d["new_clusters"]) == 0  # clusters were created «today» (now), not on Nov 10
    # the same day in another zone moves the boundary: 00:01 MSK on Nov 11 is still Nov 10 in Berlin
    assert dg.daily_digest("qtest", "2026-11-10", "Europe/Berlin")["questions"] == 8  # + «late»; «early» is Nov 9 21:00 CET


def test_daily_digest_endpoint_and_push_off(qc, monkeypatch):
    from rag_service.api.app import app

    qc.process(rec("e0", "Кто согласовывает командировку?", ts=at(11)))
    c = TestClient(app)
    r = c.get("/analytics/daily-digest", params={"date": "2026-11-10", "project_id": "qtest", "tz": "Europe/Moscow"})
    assert r.status_code == 200 and r.json()["questions"] == 1 and r.json()["type"] == "questions.daily_digest"
    assert c.get("/analytics/daily-digest", params={"date": "10.11.2026", "project_id": "qtest"}).status_code == 422
    assert c.get("/analytics/daily-digest", params={"tz": "Mars/Base", "project_id": "qtest"}).status_code == 422
    # push is off by default: no worker without DIGEST_WEBHOOK_URL
    assert not get_settings().digest_webhook_url
    dg.start_digest_worker()
    assert dg._worker is None


def test_daily_digest_push_envelope(qc, monkeypatch):
    sent = {}

    class R:
        status_code = 200

        def raise_for_status(self):
            return None

    def post(url, json, headers, timeout):
        sent.update(url=url, body=json, headers=headers)
        return R()

    import httpx

    monkeypatch.setattr(httpx, "post", post)
    s = get_settings()
    monkeypatch.setattr(s, "digest_webhook_url", "http://panel/internal/v1/events")
    monkeypatch.setattr(s, "digest_webhook_token", "tok")
    qc.process(rec("e1", "Кто согласовывает командировку?", ts=at(11)))
    out = dg.push("qtest", "2026-11-10")
    ev = sent["body"]["events"][0]
    assert out["ok"] and ev["event_id"] == "digest-qtest-2026-11-10" and ev["type"] == "questions.daily_digest"
    assert ev["data"]["questions"] == 1 and sent["headers"] == {"X-Service-Token": "tok"}
    assert dg._last_sent("qtest") == "2026-11-10"
