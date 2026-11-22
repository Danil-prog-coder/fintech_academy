"""Model routing (agent/router.py): fast tier for simple questions, heavy for the rest; OpenRouter request shape."""

from types import SimpleNamespace

import pytest

import rag_service.agent.loop as loop_mod
import rag_service.llm as llm
from rag_service.agent.memory import get_memory
from rag_service.agent.router import after_search, initial_tier
from rag_service.config import get_settings
from rag_service.tools.registry import Tools
from tests.test_agent_loop import CHUNK, IN_HOURS, call, resp


@pytest.mark.parametrize("q,tier", [
    ("Кто согласовывает БП Командировки?", "fast"),
    ("Где найти производственный календарь?", "fast"),
    ("Как настроить фильтр документа? Опиши шаги", "heavy"),
    ("Сколько дней на согласование по регламенту?", "heavy"),
    ("Чем отличается версия 3.2 от 2.4?", "heavy"),
    ("Почему не работает фильтр «!> 200»?", "heavy"),
    ("Какие статусы есть в реестре мебели?", "heavy"),
    ("Мне прислали ссылку https://bo.bars.group/#x, что это?", "heavy"),
])
def test_initial_tier(q, tier):
    assert initial_tier(q, has_images=False)[0] == tier


def test_screenshot_and_short_followup_go_heavy():
    assert initial_tier("что это?", has_images=True) == ("heavy", "screenshot")
    assert initial_tier("а в субботу?", has_images=False, standalone=False)[0] == "heavy"


def test_after_search():
    assert after_search({"max_score": 0.9, "gap_top1_top2": 0.4, "n_supporting": 1})[0]
    assert not after_search({"max_score": 0.5, "gap_top1_top2": 0.4, "n_supporting": 1})[0]
    assert not after_search({"max_score": 0.85, "gap_top1_top2": 0.05, "n_supporting": 3})[0]


def _fake(monkeypatch, score):
    models = []
    script = []

    def chat(model, **kw):
        models.append((model, kw.get("reasoning_effort")))
        r = script.pop(0)
        r._model_used = model.split(",")[0]
        return r

    def search_docs(self, query, **kw):
        self.search_calls += 1
        sid = self._register_chunk(CHUNK, score)
        sig = {"max_score": score, "gap_top1_top2": 0.5, "n_supporting": 1}
        self.search_signals.append(sig)
        return f"[{sid}] {CHUNK['text']}", {"query": query, "signals": sig}

    monkeypatch.setattr(loop_mod, "chat", chat)
    monkeypatch.setattr(loop_mod, "get_kb", lambda pid: {"docs": {"bp": {"title": "БП Командировка"}}, "images": {}})
    monkeypatch.setattr(Tools, "search_docs", search_docs)
    script += [resp(call("search_docs", {"query": "график ОМ"})),
               resp(call("final_answer", {"text": "Пн–Пт 17:30–21:00 [1].", "kind": "grounded", "coverage": "full",
                                          "citations": [{"n": 1, "source_id": "S1", "quote": "Пн–Пт 17:30–21:00"}]}))]
    return models


def test_simple_question_stays_fast(monkeypatch):
    s = get_settings()
    models = _fake(monkeypatch, 0.9)
    get_memory().reset("r1", "default")
    r = loop_mod.run_turn_sync("r1", "default", "Кто дежурит из офис-менеджеров?", now=IN_HOURS)
    assert r["action"] == "answer" and r["tier"] == "fast"
    assert [m for m, _ in models] == [s.fast_model, s.fast_model]
    assert models[0][1] == s.fast_reasoning_effort


def test_weak_search_moves_turn_to_heavy(monkeypatch):
    s = get_settings()
    models = _fake(monkeypatch, 0.62)
    get_memory().reset("r2", "default")
    r = loop_mod.run_turn_sync("r2", "default", "Кто дежурит из офис-менеджеров?", now=IN_HOURS)
    assert r["tier"] == "heavy" and any("weak search" in x for x in r["route"])
    assert [m for m, _ in models] == [s.fast_model, s.heavy_model]


def test_openrouter_provider_pin_and_reasoning(monkeypatch):
    sent = []

    def create(model, messages, **kw):
        sent.append((model, kw))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, cost=0.0004))

    monkeypatch.setattr(get_settings(), "llm_provider", "openrouter")
    monkeypatch.setattr(llm, "client", lambda prov=None: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    r = llm.chat(model="deepseek/deepseek-v4.1-flash-1017@Baseten", messages=[{"role": "user", "content": "x"}], reasoning_effort="none")
    model, kw = sent[0]
    assert model == "deepseek/deepseek-v4.1-flash-1017" and "reasoning_effort" not in kw
    assert kw["extra_body"]["provider"] == {"only": ["Baseten"], "sort": "throughput", "allow_fallbacks": False}
    assert kw["extra_body"]["reasoning"] == {"effort": "none"}
    assert llm.usage_cost(r) == 0.0004
    llm.chat(model="z-ai/glm-5.3-flash", messages=[{"role": "user", "content": "x"}], reasoning_effort="none")
    assert "reasoning" not in (sent[1][1].get("extra_body") or {})  # GLM: reasoning cannot be switched off
