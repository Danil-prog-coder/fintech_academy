"""The LLM reranker has its own time budget: a stalled provider falls back to the fused order (NFR-01)."""

import json
import time
from types import SimpleNamespace

import rag_service.retrieval.rerank as rerank
from rag_service.core.config import get_settings
from rag_service.llm import LLMUnavailable

CANDS = [{"text": f"фрагмент {i}", "chunk_type": "text", "section_path_str": f"Док → {i}"} for i in range(3)]


def reply(scores):
    content = json.dumps({"scores": [{"i": i, "s": s} for i, s in enumerate(scores)]})
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_scores_normalised(monkeypatch):
    monkeypatch.setattr(rerank, "chat", lambda **kw: reply([10, 4, 0]))
    assert rerank.llm_rerank("запрос", CANDS) == [1.0, 0.4, 0.0]
    assert rerank.llm_rerank("запрос", []) == []


def test_slow_provider_falls_back_within_budget(monkeypatch):
    monkeypatch.setattr(get_settings(), "rerank_timeout_s", 0.3)

    def slow(**kw):
        time.sleep(2)
        return reply([10, 4, 0])

    monkeypatch.setattr(rerank, "chat", slow)
    t0 = time.time()
    assert rerank.llm_rerank("запрос", CANDS) is None  # caller keeps the fused (RRF) order
    assert time.time() - t0 < 1.0


def test_no_budget_waits(monkeypatch):
    monkeypatch.setattr(get_settings(), "rerank_timeout_s", 0)
    monkeypatch.setattr(rerank, "chat", lambda **kw: time.sleep(0.2) or reply([7, 7, 7]))
    assert rerank.llm_rerank("запрос", CANDS) == [0.7, 0.7, 0.7]


def test_errors_and_bad_json_fall_back(monkeypatch):
    def down(**kw):
        raise LLMUnavailable("402")

    monkeypatch.setattr(rerank, "chat", down)
    assert rerank.llm_rerank("запрос", CANDS) is None
    bad = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="не JSON"))])
    monkeypatch.setattr(rerank, "chat", lambda **kw: bad)
    assert rerank.llm_rerank("запрос", CANDS) is None


def test_usage_reaches_the_turn_meter(monkeypatch):
    from rag_service.llm import _record_usage, usage_scope

    def counted(**kw):
        _record_usage("rerank-model", SimpleNamespace(prompt_tokens=100, completion_tokens=10), 0.001)
        return reply([5, 5, 5])

    monkeypatch.setattr(rerank, "chat", counted)
    monkeypatch.setattr(get_settings(), "rerank_timeout_s", 2.0)
    with usage_scope() as meter:
        rerank.llm_rerank("запрос", CANDS)
    assert meter["rerank-model"]["prompt_tokens"] == 100 and meter["rerank-model"]["cost"] == 0.001
