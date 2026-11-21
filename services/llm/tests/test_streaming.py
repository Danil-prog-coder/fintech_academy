"""Real streaming (NFR-01): paragraphs of the final answer are checked and emitted while the model writes."""

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import rag_service.agent.loop as loop_mod
from rag_service.agent.memory import get_memory
from rag_service.agent.streaming import StreamingGuard, partial_json_object
from rag_service.llm import _consume_stream, usage_scope
from rag_service.tools.registry import Tools

IN_HOURS = datetime(2026, 11, 16, 11, 0, tzinfo=ZoneInfo("Europe/Moscow"))
CHUNK = {"chunk_id": "c1", "doc_id": "d", "document_title": "Док", "section_path": ["1 Раздел"],
         "section_path_str": "Док → 1 Раздел", "chunk_type": "text", "image_ids": [],
         "text": "Дежурство: Пн–Пт 17:30–21:00. Телефон дежурного указан в карточке."}
REG = {"S1": {"kind": "chunk", "text": CHUNK["text"], "score": 0.9}}


def test_partial_json_object():
    done, key, part = partial_json_object('{"kind": "grounded", "citations": [{"n": 1, "source_id": "S1"}], "text": "Перв')
    assert done == {"kind": "grounded", "citations": [{"n": 1, "source_id": "S1"}]} and key == "text" and part == "Перв"
    assert partial_json_object('{"kind": "grou') == ({}, "kind", "grou")
    assert partial_json_object('{"text": "a\\n\\nb \\"q\\" \\')[2] == 'a\n\nb "q" '
    assert partial_json_object('{"text": "ok", "n": 12') == ({"text": "ok"}, None, "")  # a number may still grow
    assert partial_json_object('{"text": "ok", "n": 12}')[0] == {"text": "ok", "n": 12}
    assert partial_json_object("") == ({}, None, "")


def _feed(guard, args: dict, step: int = 7, start: int = 0):
    raw = json.dumps(args, ensure_ascii=False)
    for i in range(start + step, len(raw) + step, step):
        guard.on_delta({"type": "tool", "index": 0, "name": "final_answer", "arguments": raw[:i]})


def test_guard_emits_verified_paragraphs_before_the_answer_is_complete():
    out = []
    g = StreamingGuard(REG, "вопрос", 0.35, out.append)
    args = {"kind": "grounded", "coverage": "full", "citations": [{"n": 1, "source_id": "S1", "quote": "Пн–Пт 17:30–21:00"}],
            "text": "Дежурство по будням [1].\n\nВремя: 17:30–21:00 [1].\n\nТелефон — в карточке [1]."}
    raw = json.dumps(args, ensure_ascii=False)
    cut = raw.index("Телефон")
    g.on_delta({"type": "tool", "index": 0, "name": "final_answer", "arguments": raw[:cut]})
    # two paragraphs are complete and already shown, the third is still being written
    assert [e["text"] for e in out] == ["Дежурство по будням [1].\n\n", "Время: 17:30–21:00 [1].\n\n"]
    _feed(g, args, start=cut)
    assert g.emitted == args["text"] and not g.held and all(e["type"] == "delta" for e in out)


def test_guard_holds_back_unverified_text():
    for bad in ("Дежурство до 23:45 [1].\n\nЕщё абзац [1].",  # number that is not in the sources
                "Смотрите [3].\n\nЕщё [1].",  # marker without a citation
                "По данным [S1] всё так.\n\nЕщё [1]."):  # raw source id instead of [N]
        out = []
        g = StreamingGuard(REG, "вопрос", 0.35, out.append)
        _feed(g, {"kind": "grounded", "coverage": "full", "citations": [{"n": 1, "source_id": "S1", "quote": ""}], "text": bad})
        assert out == [] and g.held, bad
    # weak evidence or a source that was never returned by a tool: nothing is streamed at all
    for reg, cits in (({"S1": {"kind": "chunk", "text": "t", "score": 0.1}}, [{"n": 1, "source_id": "S1"}]),
                      (REG, [{"n": 1, "source_id": "S9"}]),
                      ({"T1": {"kind": "tool", "text": "t", "score": 1.0}}, [{"n": 1, "source_id": "T1"}])):
        out = []
        g = StreamingGuard(reg, "", 0.35, out.append)
        _feed(g, {"kind": "grounded", "coverage": "full", "citations": cits, "text": "Абзац [1].\n\nВторой [1]."})
        assert out == [] and g.held
    # text before citations cannot be checked on the fly
    out = []
    g = StreamingGuard(REG, "", 0.35, out.append)
    _feed(g, {"kind": "grounded", "text": "Абзац [1].\n\nВторой [1].", "citations": [{"n": 1, "source_id": "S1"}]})
    assert out == []


def test_guard_reset_and_small_talk():
    out = []
    g = StreamingGuard({}, "", 0.35, out.append)
    _feed(g, {"kind": "no_facts", "coverage": "none", "text": "Здравствуйте!\n\nЧем могу помочь?"})
    assert "".join(e["text"] for e in out) == "Здравствуйте!\n\nЧем могу помочь?"
    g.on_delta({"type": "restart"})  # another model of the chain starts over
    assert out[-1] == {"type": "reset"} and g.emitted == ""


def test_consume_stream_assembles_tool_calls_and_usage():
    def chunk(tool=None, content=None, usage=None):
        delta = SimpleNamespace(content=content, tool_calls=[tool] if tool else None)
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)] if (tool or content) else [], usage=usage)

    def tc(args, name=None, cid=None):
        return SimpleNamespace(index=0, id=cid, function=SimpleNamespace(name=name, arguments=args), model_extra={})

    seen = []
    resp = _consume_stream([chunk(tc('{"query": ', "search_docs", "call_1")), chunk(tc('"график"}')),
                            chunk(usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3))], seen.append)
    call = resp.choices[0].message.tool_calls[0]
    assert (call.id, call.function.name, json.loads(call.function.arguments)) == ("call_1", "search_docs", {"query": "график"})
    assert resp.usage.prompt_tokens == 7 and seen[-1]["arguments"] == '{"query": "график"}'


# ---------------------------------------------------------------- the loop with a streaming fake LLM
def _call(name, args, cid="c"):
    return SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=json.dumps(args, ensure_ascii=False)))


def _resp(*calls):
    msg = SimpleNamespace(content="", tool_calls=list(calls), model_dump=lambda **k: {})
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)


@pytest.fixture
def fake(monkeypatch):
    script: list = []

    def chat(**kw):
        item = script.pop(0)
        on_delta = kw.get("on_delta")
        if on_delta:  # stream the arguments in small pieces, like a provider would
            for c in item.choices[0].message.tool_calls:
                raw = c.function.arguments
                for i in range(9, len(raw) + 9, 9):
                    on_delta({"type": "tool", "index": 0, "name": c.function.name, "arguments": raw[:i]})
        return item

    def search_docs(self, query, **kw):
        self.search_calls += 1
        sid = self._register_chunk(CHUNK, 0.9)
        self.search_signals.append({"max_score": 0.9, "gap_top1_top2": 0.3, "n_supporting": 1})
        return f"[{sid}] {CHUNK['text']}", {"query": query, "chunks": [{"source_id": sid, "document": "Док", "text": CHUNK["text"]}]}

    monkeypatch.setattr(loop_mod, "chat", chat)
    monkeypatch.setattr(loop_mod, "get_kb", lambda pid: {"docs": {"d": {"title": "Док"}}, "images": {}})
    monkeypatch.setattr(Tools, "search_docs", search_docs)
    return script


def _events(msg, sid, debug=False):
    get_memory().reset(sid, "default")
    return list(loop_mod.run_turn_stream(sid, "default", msg, now=IN_HOURS, debug=debug))


GOOD = {"kind": "grounded", "coverage": "full", "citations": [{"n": 1, "source_id": "S1", "quote": "Пн–Пт 17:30–21:00"}],
        "text": "Дежурство по будням [1].\n\nВремя: 17:30–21:00 [1]."}


def test_answer_is_streamed_then_completed_with_sources(fake):
    fake += [_resp(_call("search_docs", {"query": "график"})), _resp(_call("final_answer", GOOD))]
    evs = _events("Какой график дежурства?", "st1", debug=True)
    kinds = [e["type"] for e in evs]
    assert "reset" not in kinds and kinds[-1] == "final"
    deltas = [e["text"] for e in evs if e["type"] == "delta"]
    assert deltas[0] == "Дежурство по будням [1].\n\n"  # shown before the whole answer was generated
    final = evs[-1]
    assert "".join(deltas) == final["formatted_text"] and "Источник: Док" in final["formatted_text"]
    assert final["first_token_ms"] <= final["latency_ms"]
    # the run-format tool log: the search with the fragments the model saw
    assert final["tool_log"][0]["tool"] == "search_docs" and final["tool_log"][0]["results"][0]["text"] == CHUNK["text"]
    assert "tool_log" not in _events_no_debug(fake)


def _events_no_debug(fake):
    fake += [_resp(_call("search_docs", {"query": "график"})), _resp(_call("final_answer", GOOD))]
    return _events("Какой график дежурства?", "st1b")[-1]


def test_failed_later_paragraph_resets_what_was_shown(fake):
    bad = dict(GOOD, text="Дежурство по будням [1].\n\nЗвоните до 23:45 [1].")
    fake += [_resp(_call("search_docs", {"query": "график"})), _resp(_call("final_answer", bad)), _resp(_call("final_answer", GOOD))]
    evs = _events("Какой график дежурства?", "st2")
    kinds = [e["type"] for e in evs]
    i = kinds.index("reset")
    assert "delta" in kinds[:i]  # the first paragraph was valid and shown, then withdrawn
    after = "".join(e["text"] for e in evs[i + 1:] if e["type"] == "delta")
    assert after == evs[-1]["formatted_text"] and "23:45" not in after


def test_streaming_can_be_switched_off(fake, monkeypatch):
    from rag_service.config import get_settings

    monkeypatch.setattr(get_settings(), "agent_streaming", False)
    fake += [_resp(_call("search_docs", {"query": "график"})), _resp(_call("final_answer", GOOD))]
    evs = _events("Какой график дежурства?", "st3")
    assert "reset" not in [e["type"] for e in evs]
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == evs[-1]["formatted_text"]


def test_usage_meter_collects_tokens_per_model():
    from rag_service.analytics.query_logger import cost_of
    from rag_service.config import get_settings
    from rag_service.llm import _record_usage

    with usage_scope() as meter:
        _record_usage("m1", SimpleNamespace(prompt_tokens=1000, completion_tokens=100))
        _record_usage("m1", SimpleNamespace(prompt_tokens=500, completion_tokens=50))
        _record_usage("m2", None)
    assert meter["m1"] == {"prompt_tokens": 1500, "completion_tokens": 150, "calls": 2} and meter["m2"]["calls"] == 1
    s = get_settings()
    old = s.model_prices
    try:
        s.model_prices = ""
        assert cost_of(meter) == (None, "unknown")
        s.model_prices = '{"m1": [2.0, 10.0]}'
        assert cost_of(meter) == (0.0045, "partial")
        s.model_prices = '{"m1": [2.0, 10.0], "m2": [1, 1]}'
        assert cost_of(meter) == (0.0045, "known")
    finally:
        s.model_prices = old
