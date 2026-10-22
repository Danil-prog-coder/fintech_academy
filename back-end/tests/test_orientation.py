import json
from types import SimpleNamespace

import httpx
import pytest
import respx

from app.llm.base import LLMAuthError, LLMResponseError
from app.llm.cloudru import CloudRuEmbeddings
from app.schemas.common import AnswerStatus
from app.services.orientation import MAX_QUERIES, parse_expansion
from app.services.qa import _chat_reply
from app.services.retrieval import Hit

BASE = "https://cloud.test/v1"


def test_parse_expansion_reads_queries_and_overview():
    text = 'Вот: {"queries": ["описание проекта", " стек ", 5, ""], "overview": true}'
    assert parse_expansion(text) == (["описание проекта", "стек"], True)


def test_parse_expansion_limits_number_of_queries():
    queries, _ = parse_expansion('{"queries": ["a", "b", "c", "d", "e"]}')
    assert len(queries) == MAX_QUERIES


@pytest.mark.parametrize("text", ["", "не json", '{"status": "not_found"}', '{"queries": "x"}'])
def test_parse_expansion_garbage_falls_back_to_empty(text):
    assert parse_expansion(text)[0] == []
    assert parse_expansion(text)[1] is False


def _embeddings(**kwargs) -> CloudRuEmbeddings:
    return CloudRuEmbeddings(
        httpx.AsyncClient(), "key", BASE, model="m", dim=3, batch_size=2, backoff_sec=0, **kwargs
    )


@respx.mock
async def test_cloudru_embeds_in_batches_and_keeps_order():
    def reply(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.read())["input"]
        data = [{"index": i, "embedding": [float(len(t)), 0.0, 0.0]} for i, t in enumerate(inputs)]
        return httpx.Response(200, json={"data": list(reversed(data))})  # порядок перепутан

    route = respx.post(f"{BASE}/embeddings").mock(side_effect=reply)
    vectors = await _embeddings(max_retries=0).embed(["a", "bb", "ccc"])
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0]
    assert route.call_count == 2  # пакеты по 2 текста
    assert route.calls[0].request.headers["Authorization"] == "Bearer key"


@respx.mock
async def test_cloudru_rejects_wrong_dimension():
    respx.post(f"{BASE}/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})
    )
    with pytest.raises(LLMResponseError):
        await _embeddings(max_retries=0).embed(["a"])


@respx.mock
async def test_cloudru_maps_auth_and_payment_errors():
    respx.post(f"{BASE}/embeddings").mock(return_value=httpx.Response(401))
    with pytest.raises(LLMAuthError):
        await _embeddings(max_retries=0).embed(["a"])
    respx.post(f"{BASE}/embeddings").mock(return_value=httpx.Response(402, text="Not enough money"))
    with pytest.raises(LLMResponseError):
        await _embeddings(max_retries=0).embed(["a"])


class _StubLLM:
    name = "stub"

    def __init__(self, text: str):
        self.text, self.calls = text, []

    async def complete(self, messages, **kwargs):
        self.calls.append(messages)
        return SimpleNamespace(text=self.text, provider="stub")


def _hit(n: int) -> Hit:
    chunk = SimpleNamespace(
        id=n, path=f"src/f{n}.py", kind="code", text="code", start_line=1, end_line=2,
        commit_sha="a" * 40, meta={},
    )
    return Hit(chunk, 0.5)


async def test_chat_reply_returns_plain_answer_and_cited_sources():
    repo = SimpleNamespace(owner="o", name="p", url="https://github.com/o/p", last_commit="abc")
    llm = _StubLLM("Это сервис ответов по репозиторию [2]. Запускается через docker [9].")
    result = await _chat_reply(llm, repo, "в чем суть?", [("user", "привет")], "", [_hit(1), _hit(2)])
    assert result.status == AnswerStatus.answered
    assert [s.path for s in result.sources] == ["src/f2.py"]  # [9] вне диапазона отброшен
    assert "в чем суть?" in llm.calls[0][1].content


async def test_chat_reply_without_citations_is_still_answered():
    repo = SimpleNamespace(owner="o", name="p", url="u", last_commit="abc")
    result = await _chat_reply(_StubLLM("Привет! Чем помочь?"), repo, "привет", None, "", [])
    assert result.status == AnswerStatus.answered and result.sources == []


async def test_chat_reply_empty_answer_is_an_error():
    repo = SimpleNamespace(owner="o", name="p", url="u", last_commit="abc")
    with pytest.raises(LLMResponseError):
        await _chat_reply(_StubLLM("  "), repo, "привет", None, "", [])
