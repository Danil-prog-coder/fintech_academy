"""AgentLoop with a scripted fake LLM: final actions, guardrail retry, fallbacks (no network)."""

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import rag_service.agent.loop as loop_mod
from rag_service.agent.memory import get_memory
from rag_service.llm import LLMUnavailable
from rag_service.tools.registry import Tools

IN_HOURS = datetime(2026, 11, 16, 11, 0, tzinfo=ZoneInfo("Europe/Moscow"))
CHUNK = {"chunk_id": "c1", "doc_id": "bp", "document_title": "БП Командировка", "section_path": ["1 Содержание"],
         "section_path_str": "БП Командировка → 1 Содержание", "chunk_type": "text", "image_ids": [],
         "text": "Дежурство ОМ: Пн–Пт 17:30–21:00, Сб–Вс 10:30–21:00."}


def call(name, args, cid="c"):
    return SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=json.dumps(args, ensure_ascii=False)))


def resp(*calls):
    msg = SimpleNamespace(content="", tool_calls=list(calls), model_dump=lambda **k: {})
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


@pytest.fixture
def fake(monkeypatch):
    script: list = []

    def chat(**kw):
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def search_docs(self, query, **kw):
        self.search_calls += 1
        sid = self._register_chunk(CHUNK, 0.9)
        self.search_signals.append({"max_score": 0.9, "gap_top1_top2": 0.3, "n_supporting": 1})
        return f"[{sid}] {CHUNK['text']}", {"query": query}

    monkeypatch.setattr(loop_mod, "chat", chat)
    monkeypatch.setattr(loop_mod, "get_kb", lambda pid: {"docs": {"bp": {"title": "БП Командировка"}}, "images": {}})
    monkeypatch.setattr(Tools, "search_docs", search_docs)
    return script


def run(msg, sid="s"):
    get_memory().reset(sid, "default")
    return loop_mod.run_turn_sync(sid, "default", msg, now=IN_HOURS)


def test_grounded_answer(fake):
    fake += [resp(call("search_docs", {"query": "график ОМ"})),
             resp(call("final_answer", {"text": "Пн–Пт 17:30–21:00 [1].", "kind": "grounded", "coverage": "full",
                                        "citations": [{"n": 1, "source_id": "S1", "quote": "Пн–Пт 17:30–21:00"}]}))]
    r = run("Какой график офис-менеджера?")
    assert r["action"] == "answer" and r["confidence_level"] in ("high", "medium")
    assert r["sources"][0]["excerpt"] == "Пн–Пт 17:30–21:00"
    assert "Источник: БП Командировка" in r["formatted_text"]


def test_answer_without_search_is_retried_then_offer(fake):
    bad = call("final_answer", {"text": "Дежурство до 23:00 [1].", "kind": "grounded", "coverage": "full",
                                "citations": [{"n": 1, "source_id": "S1", "quote": "x"}]})
    fake += [resp(bad), resp(bad)]
    r = run("Какой график офис-менеджера?")
    assert r["action"] == "offer_operator"
    assert r["text"].startswith("Я пока не нашёл точного ответа. Переключить на оператора?")
    assert r["buttons"][0]["text"] == "Связаться с поддержкой"


def test_hallucinated_number_retried_once(fake):
    fake += [resp(call("search_docs", {"query": "график"})),
             resp(call("final_answer", {"text": "До 23:00 [1].", "kind": "grounded", "coverage": "full",
                                        "citations": [{"n": 1, "source_id": "S1", "quote": ""}]})),
             resp(call("final_answer", {"text": "До 21:00 [1].", "kind": "grounded", "coverage": "full",
                                        "citations": [{"n": 1, "source_id": "S1", "quote": ""}]}))]
    r = run("До скольки дежурит ОМ?")
    assert r["action"] == "answer" and "21:00" in r["text"]


def test_operator_request_bypasses_llm(fake):
    r = run("Позовите живого человека")
    assert r["action"] == "escalate" and r["reason"] == "user_request" and r["summary"]
    assert fake == []  # no LLM call was needed


def test_llm_unavailable_offers_operator(fake):
    fake += [LLMUnavailable("429")]
    r = run("Кто согласовывает БП?")
    assert r["action"] == "offer_operator" and r["reason"] == "llm_unavailable"


def test_no_facts_smalltalk(fake):
    fake += [resp(call("final_answer", {"text": "Я отвечаю только по документации БАРС-Офиса 🙂", "kind": "no_facts", "coverage": "none"}))]
    r = run("Какая погода в Казани?")
    assert r["action"] == "answer" and r["sources"] == []


def test_clarify(fake):
    # 15.11: a clarification before any search is sent back once («look in the docs first»); after a search it stands
    ask = resp(call("ask_clarification", {"question": "Какое подразделение выбрано?", "options": ["Бизнес-центр", "Служба"]}))
    fake += [ask, resp(call("search_docs", {"query": "выбор сделки"})), ask]
    r = run("Почему не выбирается сделка?")
    assert r["action"] == "clarify" and [b["text"] for b in r["buttons"]] == ["Бизнес-центр", "Служба"] and r["search_calls"] == 1


def test_search_limit_forces_final(fake):
    fake += [resp(call("search_docs", {"query": f"q{i}"}, f"c{i}")) for i in range(4)]
    fake += [resp(call("offer_operator", {"reason": "no_answer_in_docs"}))]
    r = run("Сложный вопрос")
    assert r["action"] == "offer_operator" and r["search_calls"] == 4


def test_dangling_marker_dropped_on_second_attempt(fake):
    fa = {"text": "Пн–Пт 17:30–21:00 [1], подробнее [7].", "kind": "grounded", "coverage": "full",
          "citations": [{"n": 1, "source_id": "S1", "quote": "Пн–Пт 17:30–21:00"}]}
    fake += [resp(call("search_docs", {"query": "график"})), resp(call("final_answer", fa)), resp(call("final_answer", fa))]
    r = run("График ОМ?")
    assert r["action"] == "answer" and "[7]" not in r["text"]


IMAGE_CHUNK = {"chunk_id": "c2", "doc_id": "bp", "document_title": "БП Командировка", "section_path": ["2 Схема"],
               "section_path_str": "БП Командировка → 2 Схема", "chunk_type": "image", "image_ids": ["bp/p04_01_Image60"],
               "text": "Описание изображения: «Офис Казанский?» — Нет → «Офис менеджер»."}


@pytest.fixture
def with_schema(fake, monkeypatch):
    def search_docs(self, query, **kw):
        self.search_calls += 1
        sid_text = self._register_chunk(CHUNK, 0.9)
        sid_img = self._register_chunk(IMAGE_CHUNK, 0.9)
        self.search_signals.append({"max_score": 0.9, "gap_top1_top2": 0.3, "n_supporting": 2})
        return f"[{sid_text}] {CHUNK['text']}\n[{sid_img}] {IMAGE_CHUNK['text']}", {"query": query}

    monkeypatch.setattr(Tools, "search_docs", search_docs)
    monkeypatch.setattr(loop_mod, "get_kb", lambda pid: {"docs": {"bp": {"title": "БП Командировка"}},
                                                         "images": {"bp/p04_01_Image60": {"kind": "bpmn", "title": "Схема"}}})
    return fake


def test_cited_image_fragment_attaches_the_picture(with_schema):
    """FR-VIS-02: the agent cited the diagram's description but did not pass image_ids — the code attaches it."""
    with_schema += [resp(call("search_docs", {"query": "схема офис"})),
                    resp(call("final_answer", {"text": "Если офис не Казанский — сразу «Офис менеджер» [1].", "kind": "grounded",
                                               "coverage": "full", "citations": [{"n": 1, "source_id": "S2", "quote": "Нет → «Офис менеджер»"}]}))]
    r = run("Что если офис не Казанский?")
    assert r["action"] == "answer" and r["image_ids"] == ["bp/p04_01_Image60"]
    assert r["image_meta"][0]["document_title"] == "БП Командировка" and r["image_meta"][0]["kind"] == "bpmn"


def test_text_only_answer_attaches_nothing(with_schema, monkeypatch):
    with_schema += [resp(call("search_docs", {"query": "график"})),
                    resp(call("final_answer", {"text": "Пн–Пт 17:30–21:00 [1].", "kind": "grounded", "coverage": "full",
                                               "citations": [{"n": 1, "source_id": "S1", "quote": "Пн–Пт 17:30–21:00"}]}))]
    assert run("Какой график?")["image_ids"] == []


def test_attach_switch_off(with_schema, monkeypatch):
    monkeypatch.setattr(loop_mod.get_settings(), "attach_cited_images", False)
    with_schema += [resp(call("search_docs", {"query": "схема"})),
                    resp(call("final_answer", {"text": "Сразу «Офис менеджер» [1].", "kind": "grounded", "coverage": "full",
                                               "citations": [{"n": 1, "source_id": "S2", "quote": "Нет → «Офис менеджер»"}]}))]
    assert run("Что если офис не Казанский?")["image_ids"] == []


def test_deterministic_tool_output_is_not_sanitized(fake, monkeypatch):
    """The guard hides instruction-like sentences in documents only; our own tools' output reaches the model whole."""
    seen = {}
    monkeypatch.setattr(loop_mod, "sanitize_untrusted", lambda text: ("[скрыто]", 1))
    monkeypatch.setattr(Tools, "execute", lambda self, name, args: seen.setdefault(name, (f"вывод {name}", {})))
    loop = loop_mod.AgentLoop("s", "default")
    tools = Tools("default", {"registry": {}, "messages": []})
    assert loop._run_tool(tools, "parse_bo_link", {"url": "x"})[0] == "вывод parse_bo_link"
    assert loop._run_tool(tools, "validate_filter", {"expression": "!> 200"})[0] == "вывод validate_filter"
    assert loop._run_tool(tools, "search_docs", {"query": "q"})[0] == "[скрыто]"


def test_no_facts_on_domain_question_without_search_is_retried(fake):
    """eval 15.11 (TC-08): a counter-question as «no_facts» before any search → one retry that searches first."""
    fake += [resp(call("final_answer", {"text": "Уточните, о какой системе речь?", "kind": "no_facts", "coverage": "none"})),
             resp(call("search_docs", {"query": "график ОМ"})),
             resp(call("final_answer", {"text": "Сб–Вс 10:30–21:00 [1].", "kind": "grounded", "coverage": "full",
                                        "citations": [{"n": 1, "source_id": "S1", "quote": "Сб–Вс 10:30–21:00"}]}))]
    r = run("Смогу ли я запустить БП Командировка без бюджета?")
    assert r["action"] == "answer" and r["sources"] and r["search_calls"] == 1


def test_no_facts_small_talk_is_not_retried(fake):
    fake += [resp(call("final_answer", {"text": "Здравствуйте! Чем помочь?", "kind": "no_facts", "coverage": "none"}))]
    assert run("привет")["action"] == "answer" and not fake


def test_clarification_before_any_search_is_retried(fake):
    fake += [resp(call("ask_clarification", {"question": "О каком подразделении речь?", "options": ["А", "Б"]})),
             resp(call("search_docs", {"query": "график ОМ"})),
             resp(call("final_answer", {"text": "Пн–Пт 17:30–21:00 [1].", "kind": "grounded", "coverage": "full",
                                        "citations": [{"n": 1, "source_id": "S1", "quote": "Пн–Пт 17:30–21:00"}]}))]
    r = run("Какой график работы у офис-менеджера в БП Командировка?")
    assert r["action"] == "answer" and r["search_calls"] == 1


def test_own_tool_output_is_not_sanitized(monkeypatch):
    """15.11: «Система: БАРС-Офис (bo.bars.group)» from parse_bo_link was hidden by the injection filter as «system:»."""
    from rag_service.config import get_settings

    monkeypatch.setattr(get_settings(), "guard_enabled", True)
    line = "Система: БАРС-Офис (bo.bars.group)"
    tools = SimpleNamespace(execute=lambda name, args: (line, {}))
    agent = loop_mod.AgentLoop.__new__(loop_mod.AgentLoop)
    assert agent._run_tool(tools, "parse_bo_link", {})[0] == line
    assert "скрыт" in agent._run_tool(tools, "search_docs", {})[0]

