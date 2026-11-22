"""LLM provider routing / 429-502 fallback (OpenRouter GLM → Gemini) and FAQ level-2 serving (FR-FAQ-04/06)."""

from types import SimpleNamespace

import httpx
import pytest
from openai import InternalServerError, RateLimitError

import rag_service.llm as llm
import rag_service.service as service
from rag_service.agent.memory import get_memory


def _err(cls, code):
    r = httpx.Response(code, request=httpx.Request("POST", "https://x"))
    return cls("err", response=r, body=None)


def test_split_model():
    assert llm.split_model("gemini/gemini-3.5-flash") == ("gemini", "gemini-3.5-flash")
    assert llm.split_model("z-ai/glm-5.3-flashx-legal")[1] == "z-ai/glm-5.3-flashx-legal"


@pytest.mark.parametrize("cls,code", [(RateLimitError, 429), (InternalServerError, 502)])
def test_single_provider_model_retry_then_fallback(monkeypatch, cls, code):
    calls = []

    def create(model, messages, **kw):
        calls.append(model)
        if model.startswith("z-ai/"):
            raise _err(cls, code)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    monkeypatch.setattr(llm, "client", lambda prov=None: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    llm._cooldown.clear()
    r = llm.chat(model="z-ai/glm-5.3-flashx-legal,gemini/gemini-flash-lite-latest", messages=[{"role": "user", "content": "hi"}])
    assert r._model_used == "gemini/gemini-flash-lite-latest"
    assert calls == ["z-ai/glm-5.3-flashx-legal", "z-ai/glm-5.3-flashx-legal", "gemini-flash-lite-latest"]  # one retry, then fallback
    llm._cooldown.clear()


def test_gemini_gets_thought_signature_for_foreign_tool_calls():
    msgs = [{"role": "assistant", "content": "", "tool_calls": [{"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]}]
    out = llm._gemini_compatible(msgs)
    assert out[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"]
    assert "extra_content" not in msgs[0]["tool_calls"][0]  # original history is not mutated


def test_json_content_tolerates_fences():
    r = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='```json\n{"equivalent": true}\n```'))])
    assert llm.json_content(r) == {"equivalent": True}


def test_faq_level2_hit_served_and_kept_in_history(monkeypatch):
    entry = {"id": "e1", "question": "Кто согласовывает БП Командировки?", "origin": "manual",
             "answer": {"action": "answer", "text": "Руководитель [1]", "sources": [{"citation_label": "[1]", "source_id": "S1", "document_title": "БП Командировка", "section_path": "БП → 4", "excerpt": "руководитель", "chunk_type": "text", "image_ids": []}],
                        "image_ids": [], "confidence": 0.9, "confidence_level": "high"}}
    served = []
    fake_faq = SimpleNamespace(lookup=lambda pid, gen, q: {"entry": entry, "score": 0.93, "matched": entry["question"]},
                               mark_served=lambda pid, eid: served.append(eid))
    monkeypatch.setattr(service, "get_faq", lambda: fake_faq)
    monkeypatch.setattr(service.store, "active_generation", lambda pid: "g1")
    monkeypatch.setattr(service, "run_turn_stream", lambda *a, **k: (_ for _ in ()).throw(AssertionError("agent must not run")))
    get_memory().reset("faq-u", "default")
    events = list(service.ask_events("faq-u", "default", "кто согласует командировку?"))
    final = events[-1]
    assert final["cache_hit"] and final["cache_level"] == "faq" and final["faq_entry_id"] == "e1"
    assert served == ["e1"]
    sess = get_memory().load("faq-u", "default")
    assert [m["role"] for m in sess["messages"]][-2:] == ["user", "assistant"]  # FR-FAQ-06: follow-ups have context


def test_embedding_retry_backoff(monkeypatch):
    import rag_service.index.embeddings as emb

    assert emb._retry_pause(_err(RateLimitError, 429), 0) >= 3.0
    assert emb._retry_pause(_err(RateLimitError, 429), 3) > emb._retry_pause(_err(RateLimitError, 429), 0)
    assert emb._retry_pause(_err(InternalServerError, 503), 0) is not None
    from openai import BadRequestError

    assert emb._retry_pause(_err(BadRequestError, 400), 0) is None  # e.g. dimension mismatch: fail fast
    assert emb._retry_pause(ConnectionError("reset"), 1) is not None
