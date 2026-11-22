"""Latency flags (Docs/latency-2026-11-15.md): stalled provider → next model, turn deadline, hedged reranker,
BM25-only search when the query embedding fails. On by default in Settings; pinned off for tests in conftest.py."""

import json
import time
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError

import rag_service.llm as llm
import rag_service.retrieval.rerank as rerank
from rag_service.core.config import get_settings

OK = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])


def _chunk(text):
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))])


@pytest.fixture(autouse=True)
def _clean():
    llm._cooldown.clear()
    yield
    llm._cooldown.clear()


def _patch_client(monkeypatch, create):
    monkeypatch.setattr(llm, "client", lambda prov=None: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def test_stall_goes_to_next_model_without_same_model_retry(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_stall_timeout_s", 5.0)
    calls, timeouts = [], []

    def create(model, messages, **kw):
        calls.append(model)
        timeouts.append(kw.get("timeout"))
        if model == "a/slow":
            raise APITimeoutError(request=httpx.Request("POST", "https://x"))
        return iter([_chunk("ответ")])

    _patch_client(monkeypatch, create)
    r = llm.chat(model="a/slow,b/fast", messages=[{"role": "user", "content": "hi"}], on_delta=lambda e: None)
    assert r._model_used == "b/fast" and calls == ["a/slow", "b/fast"]
    assert timeouts[0].read == 5.0
    assert llm._cooldown.get("a/slow", 0) > time.time()


def test_stall_timeout_only_for_streams(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_stall_timeout_s", 5.0)
    seen = []
    _patch_client(monkeypatch, lambda model, messages, **kw: seen.append(kw.get("timeout")) or OK)
    llm.chat(model="a/x", messages=[{"role": "user", "content": "hi"}])
    assert seen == [None]  # non-streamed calls (indexing, reranker) keep the client timeout


def test_deadline_cap_cuts_a_stream(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_deadline_cap", True)

    def slow_stream():
        yield _chunk("а")
        time.sleep(0.8)
        yield _chunk("б")

    monkeypatch.setattr(llm, "client", lambda prov=None: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda model, messages, **kw: slow_stream()))))
    with pytest.raises(llm.LLMUnavailable):
        llm.chat(model="a/x,b/y", messages=[{"role": "user", "content": "hi"}], on_delta=lambda e: None,
                 deadline=time.time() + 0.6)


def test_production_defaults_on():
    f = type(get_settings()).model_fields
    assert (f["llm_stall_timeout_s"].default, f["llm_deadline_cap"].default, f["retrieval_dense_timeout_s"].default,
            f["rerank_hedge_after_s"].default) == (10.0, True, 4.0, 1.5)


def test_pinned_off_in_tests(monkeypatch):
    s = get_settings()
    assert (s.llm_stall_timeout_s, s.llm_deadline_cap, s.rerank_hedge_after_s, s.retrieval_dense_timeout_s) == (0.0, False, 0.0, 0.0)
    seen = []
    _patch_client(monkeypatch, lambda model, messages, **kw: seen.append("timeout" in kw) or iter([_chunk("x")]))
    llm.chat(model="a/x", messages=[{"role": "user", "content": "hi"}], on_delta=lambda e: None, deadline=time.time() + 30)
    assert seen == [False]


def _reply(scores):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=json.dumps({"scores": [{"i": i, "s": s} for i, s in enumerate(scores)]})))])


CANDS = [{"text": f"фрагмент {i}", "chunk_type": "text", "section_path_str": f"Док → {i}"} for i in range(2)]


def test_hedged_rerank_takes_the_faster_provider(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "rerank_model", "m@Slow,m@Fast")
    monkeypatch.setattr(s, "rerank_hedge_after_s", 0.1)
    monkeypatch.setattr(s, "rerank_timeout_s", 3.0)
    asked = []

    def chat(model, **kw):
        asked.append(model)
        if model == "m@Slow":
            time.sleep(1.5)
            return _reply([0, 0])
        return _reply([10, 5])

    monkeypatch.setattr(rerank, "chat", chat)
    t0 = time.time()
    assert rerank.llm_rerank("запрос", CANDS) == [1.0, 0.5]
    assert time.time() - t0 < 1.0 and asked == ["m@Slow", "m@Fast"]


def test_hedged_rerank_fast_first_model_no_hedge(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "rerank_model", "m@A,m@B")
    monkeypatch.setattr(s, "rerank_hedge_after_s", 1.0)
    asked = []
    monkeypatch.setattr(rerank, "chat", lambda model, **kw: asked.append(model) or _reply([7, 7]))
    assert rerank.llm_rerank("запрос", CANDS) == [0.7, 0.7] and asked == ["m@A"]


def test_hedged_rerank_budget(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "rerank_model", "m@A,m@B")
    monkeypatch.setattr(s, "rerank_hedge_after_s", 0.1)
    monkeypatch.setattr(s, "rerank_timeout_s", 0.4)
    monkeypatch.setattr(rerank, "chat", lambda model, **kw: time.sleep(1.5) or _reply([1, 1]))
    t0 = time.time()
    assert rerank.llm_rerank("запрос", CANDS) is None and time.time() - t0 < 1.0


class _KeepAliveStream:
    """An SSE stream that only sends keep-alive comments: the SDK yields nothing, the HTTP read timeout never fires."""

    def __init__(self):
        self.closed = False

    def __iter__(self):
        while not self.closed:
            time.sleep(0.05)
        raise httpx.ReadError("closed")

    def close(self):
        self.closed = True


def test_watchdog_drops_a_silent_stream_and_falls_back(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_stall_timeout_s", 0.5)
    calls = []

    def create(model, messages, **kw):
        calls.append(model)
        return _KeepAliveStream() if model == "a/silent" else iter([_chunk("ответ")])

    monkeypatch.setattr(llm, "client", lambda prov=None: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    t0 = time.time()
    r = llm.chat(model="a/silent,b/ok", messages=[{"role": "user", "content": "hi"}], on_delta=lambda e: None)
    assert r._model_used == "b/ok" and calls == ["a/silent", "b/ok"] and time.time() - t0 < 2.0


def test_watchdog_abandons_a_request_that_hangs_before_the_stream(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_stall_timeout_s", 0.5)
    late = []

    def create(model, messages, **kw):
        if model == "a/hang":
            time.sleep(1.5)  # e.g. headers never come in time
            return iter([_chunk("поздно")])
        return iter([_chunk("ответ")])

    monkeypatch.setattr(llm, "client", lambda prov=None: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    t0 = time.time()
    r = llm.chat(model="a/hang,b/ok", messages=[{"role": "user", "content": "hi"}], on_delta=late.append)
    assert r._model_used == "b/ok" and time.time() - t0 < 1.4
    time.sleep(1.3)
    assert all("поздно" not in (e.get("text") or "") for e in late)  # the abandoned call's output is dropped


def test_hedged_call_moves_on_at_once_when_the_first_model_fails():
    asked = []

    def call(model):
        asked.append(model)
        if model == "a":
            raise llm.LLMUnavailable("400")
        return "ok:" + model

    t0 = time.time()
    assert llm.hedged_call(call, ["a", "b", "c"], after=5.0, budget=10.0) == "ok:b,c"
    assert asked == ["a", "b,c"] and time.time() - t0 < 1.0
