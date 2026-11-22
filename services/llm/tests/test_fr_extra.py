"""FR-VIS-03 screenshot pre-pass, FR-RET-07 neighbouring steps, FR-ING-06 crops, FR-INP-02/05,
FR-AN-02..05 analytics and the new API endpoints (no network)."""

import base64
import io
import json
import time
import uuid

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import rag_service.agent.loop as loop_mod
import rag_service.analytics.store as an_store
import rag_service.api.app as app_mod
import rag_service.ingest.vision as vision
from rag_service.agent.memory import get_memory
from rag_service.analytics import classify
from rag_service.analytics import report as an
from rag_service.config import get_settings
from rag_service.ingest.crops import crop_red_frame, red_frame_bbox
from rag_service.tools.registry import Tools
from tests.test_agent_loop import CHUNK, IN_HOURS, call, fake, resp  # noqa: F401  (fixture)


# ------------------------------------------------------------------ FR-ING-06: framed area crop
def test_frame_crop(tmp_path):
    img = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 20), "Панель документа", fill="black")
    d.rectangle((150, 100, 300, 180), outline=(220, 30, 30), width=3)
    p = tmp_path / "shot.png"
    img.save(p)
    x0, y0, x1, y1 = red_frame_bbox(p)
    assert abs(x0 - 150) <= 3 and abs(y0 - 100) <= 3 and abs(x1 - 300) <= 3 and abs(y1 - 180) <= 3
    out = tmp_path / "crop.png"
    assert crop_red_frame(p, out) and Image.open(out).size[0] < 400
    plain = tmp_path / "plain.png"
    Image.new("RGB", (200, 100), "white").save(plain)
    assert red_frame_bbox(plain) is None


# ------------------------------------------------------------------ FR-RET-07: neighbouring steps
def test_neighbour_steps(monkeypatch):
    sp = "Инструкция → 3 Создание заявки"
    steps = {f"doc:{i:04d}": {"chunk_id": f"doc:{i:04d}", "doc_id": "doc", "order": i, "section_path_str": sp, "section_path": sp,
                               "chunk_type": "text", "step_label": f"Шаг {i}", "text": f"шаг {i}", "document_title": "Инструкция",
                               "image_ids": []} for i in range(1, 5)}
    steps["doc:0005"] = dict(steps["doc:0004"], chunk_id="doc:0005", order=5, section_path="Другой раздел")
    import rag_service.tools.registry as reg

    monkeypatch.setattr(reg, "get_kb", lambda pid: {"by_id": steps})
    t = Tools("default", {"registry": {}, "next_s": 1})
    out = t._neighbours([steps["doc:0002"]], ["S1"])
    assert sorted(n["chunk"]["chunk_id"] for _, n in out) == ["doc:0001", "doc:0003"]
    out = t._neighbours([steps["doc:0004"]], ["S1"])
    assert [n["chunk"]["chunk_id"] for _, n in out] == ["doc:0003"]  # step 5 is in another section


# ------------------------------------------------------------------ FR-VIS-03 + FR-INP-02
def _png_b64():
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_screenshot_prepass_reads_searches_and_remembers(fake, monkeypatch):  # noqa: F811
    seen = {}

    def fake_vlm(images, user_text, deadline):
        seen["n"] = len(images)
        return {"screen": "Реестр мебели", "error_text": "Нет прав на запись", "search_query": "нет прав на запись реестр мебели",
                "_model": "fake-vlm"}

    monkeypatch.setattr(vision, "describe_user_images", fake_vlm)
    queries = []
    orig = Tools.search_docs

    def spy(self, query, **kw):
        queries.append(query)
        return orig(self, query, **kw)

    monkeypatch.setattr(Tools, "search_docs", spy)
    fake += [resp(call("final_answer", {"text": "Пн–Пт 17:30–21:00 [1].", "kind": "grounded", "coverage": "full",
                                        "citations": [{"n": 1, "source_id": "S1", "quote": "Пн–Пт 17:30–21:00"}]}))]
    get_memory().reset("vis", "default")
    r = loop_mod.run_turn_sync("vis", "default", "что это за ошибка?", images=[{"mime": "image/png", "data_base64": _png_b64()}],
                               now=IN_HOURS)
    assert seen["n"] == 1 and queries[0] == "нет прав на запись реестр мебели"
    assert r["action"] == "answer"
    sess = get_memory().load("vis", "default")
    user_msgs = [m["content"] for m in sess["messages"] if m["role"] == "user"]
    assert "скриншот пользователя" in user_msgs[-1] and "Нет прав на запись" in user_msgs[-1]  # FR-INP-02: kept in history
    saved = list((__import__("pathlib").Path(get_settings().state_dir) / "user_images").glob("*.png"))
    assert saved


def test_history_in_followup_messages(fake, monkeypatch):  # noqa: F811
    captured = []

    def chat(**kw):
        captured.append(kw["messages"])
        return fake.pop(0)

    monkeypatch.setattr(loop_mod, "chat", chat)
    ok = resp(call("final_answer", {"text": "Пн–Пт 17:30–21:00 [1].", "kind": "grounded", "coverage": "full",
                                    "citations": [{"n": 1, "source_id": "S1", "quote": "Пн–Пт 17:30–21:00"}]}))
    fake += [resp(call("search_docs", {"query": "график ОМ"})), ok, resp(call("search_docs", {"query": "график ОМ суббота"})), ok]
    get_memory().reset("h", "default")
    loop_mod.run_turn_sync("h", "default", "Какой график офис-менеджера?", now=IN_HOURS)
    loop_mod.run_turn_sync("h", "default", "а в субботу?", now=IN_HOURS)
    contents = " ".join(m.get("content") or "" for m in captured[-1] if isinstance(m.get("content"), str))
    assert "Какой график офис-менеджера?" in contents and "а в субботу?" in contents


def test_user_parameters_rule_in_prompt():
    from pathlib import Path

    p = (Path(__file__).parents[1] / "prompts" / "agent_system.md").read_text(encoding="utf-8")
    assert "сравни данные пользователя с условием" in p  # FR-INP-05
    assert "Точные токены из вопроса" in p


# ------------------------------------------------------------------ FR-AN-02..05
def _write_turns(recs):
    an_store.write_turns(recs)  # the query log lives in the database (rag_turns)


def test_summary_success_rate_and_feedback():
    pid = "an-" + uuid.uuid4().hex[:6]
    now = time.time()
    recs = [{"ts": now - i, "request_id": f"{pid}-{i}", "project_id": pid, "session": f"s{i}", "text": t, "action": a,
             "latency_ms": 1000 * (i + 1), "sources": ["БП Командировка → 4 Согласование"], "usage": {"prompt_tokens": 100, "completion_tokens": 10}}
            for i, (t, a) in enumerate([("Кто согласует командировку?", "answer"), ("Кто согласует командировку?", "answer"),
                                        ("Позовите человека", "escalate"), ("Где календарь", "offer_operator")])]
    recs[1]["cache_hit"] = True
    recs[1]["cache_level"] = "faq"
    recs.append({"ts": now, "request_id": f"{pid}-int", "project_id": pid, "session": "faq-build-x", "text": "x", "action": "answer",
                 "internal": True})
    _write_turns(recs)
    an_store.record_feedback(f"{pid}-0", "down")
    s = an.summary(1, pid)
    assert s["requests"] == 4  # internal FAQ-build turns are excluded
    assert s["success_rate"] == 0.25  # answer without 👎: only the cached one
    assert s["escalation_rate"] == 0.5 and s["feedback"]["down"] == 1
    assert s["cache"]["by_level"] == {"faq": 1}
    ts = an.timeseries(1, "day", pid)
    assert sum(p["requests"] for p in ts["series"]) == 4
    c = TestClient(app_mod.app)
    assert c.post("/feedback", json={"request_id": "nope", "rating": "up"}).status_code == 404
    assert c.post("/feedback", json={"request_id": f"{pid}-2", "rating": "up"}).json()["ok"]
    assert c.get("/analytics/summary", params={"days": 1, "project_id": pid}).json()["feedback"]["up"] == 1


def test_rule_classifier():
    r = classify.rule_classify("Какие статусы в реестре мебели?")
    assert r["object"] and "реестр" in r["object"] and r["by"] == "rules"
    assert classify.rule_classify("Почему не работает фильтр !> 200")["type"] == "почему не работает"


def test_gaps_report(monkeypatch):
    import rag_service.faq.service as svc
    from tests.fakes import FakeEmbedder

    monkeypatch.setattr(svc, "get_embedder", lambda: FakeEmbedder())
    pid = "gap-" + uuid.uuid4().hex[:6]
    now = time.time()
    recs = [{"ts": now - i, "request_id": f"{pid}-{i}", "project_id": pid, "session": f"g{i}", "text": "Как оформить пропуск для гостя?",
             "action": "offer_operator", "standalone": True, "sources": [], "reason": "no_answer_in_docs"} for i in range(3)]
    _write_turns(recs)
    g = an.gaps(1, pid)
    assert g["questions"] == 3 and g["gaps"][0]["count"] == 3 and "пропуск" in g["gaps"][0]["question"].lower()


def test_cache_clear_levels_and_faq_endpoints(monkeypatch):
    c = TestClient(app_mod.app)
    assert c.post("/cache/clear", params={"level": "bogus"}).status_code == 422
    r = c.post("/cache/clear", params={"level": "exact"})
    assert r.status_code == 200 and "deleted" in r.json()
    assert c.get("/faq/stats").status_code == 200
    assert c.get("/faq/entries").status_code == 200
    assert c.get("/git/sources").json() == [] or isinstance(c.get("/git/sources").json(), list)
    assert c.post("/webhooks/github", content=b"{}", headers={"X-Hub-Signature-256": "sha256=00"}).status_code == 400


def test_github_webhook_signature_required(monkeypatch, tmp_path):
    import hashlib
    import hmac

    from rag_service.git_source import sources

    monkeypatch.setattr(get_settings(), "state_dir", str(tmp_path))
    src = sources.add("default", "github", "org/hookrepo", "main")
    started = []
    monkeypatch.setattr(app_mod, "_start_fn_job", lambda *a, **k: started.append(a) or {"job_id": "j1"})
    body = json.dumps({"ref": "refs/heads/main", "repository": {"full_name": "org/hookrepo"}}).encode()
    c = TestClient(app_mod.app)
    assert c.post("/webhooks/github", content=body, headers={"X-Hub-Signature-256": "sha256=00"}).status_code == 401
    sig = "sha256=" + hmac.new(src["webhook_secret"].encode(), body, hashlib.sha256).hexdigest()
    r = c.post("/webhooks/github", content=body, headers={"X-Hub-Signature-256": sig})
    assert r.status_code == 200 and r.json()["jobs"] == ["j1"] and started
