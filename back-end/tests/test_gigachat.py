import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
import respx

from app.llm.base import (
    LLMAuthError,
    LLMResponseError,
    LLMUnavailableError,
    Message,
)
from app.llm.gigachat import (
    GigaChatAuth,
    GigaChatEmbeddings,
    GigaChatProvider,
    make_ssl_context,
)

AUTH_URL = "https://auth.test/oauth"
BASE = "https://api.test/v1"
DIM = 4


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def token_response(token="tok-1", ttl=1800, clock=None):
    now = clock() if clock else 1_000_000.0
    return httpx.Response(200, json={"access_token": token, "expires_at": int((now + ttl) * 1000)})


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as c:
        yield c


def make(http, clock, **kw):
    auth = GigaChatAuth(http, "Basic KEY==", "GIGACHAT_API_PERS", AUTH_URL, clock=clock)
    common = {"max_retries": 2, "backoff_sec": 0}
    llm = GigaChatProvider(http, auth, BASE, model="GigaChat", **common)
    emb = GigaChatEmbeddings(
        http, auth, BASE, model="Embeddings", dim=DIM, batch_size=2, concurrency=2, **common
    )
    return auth, llm, emb


def chat_ok(text="привет"):
    return httpx.Response(
        200,
        json={
            "model": "GigaChat:1",
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        },
    )


@respx.mock
async def test_auth_request_shape_and_token_cache(http, clock):
    oauth = respx.post(AUTH_URL).mock(return_value=token_response(clock=clock))
    auth, _, _ = make(http, clock)
    assert await auth.get_token() == "tok-1"
    assert await auth.get_token() == "tok-1"  # из кэша
    assert oauth.call_count == 1
    req = oauth.calls[0].request
    assert req.headers["Authorization"] == "Basic KEY=="  # префикс не дублируется
    assert req.headers["RqUID"]
    assert req.content == b"scope=GIGACHAT_API_PERS"


@respx.mock
async def test_token_refreshed_before_expiry(http, clock):
    oauth = respx.post(AUTH_URL).mock(
        side_effect=[token_response("t1", clock=clock), token_response("t2", clock=clock)]
    )
    auth, _, _ = make(http, clock)
    assert await auth.get_token() == "t1"
    clock.now += 1800 - 30  # до истечения меньше запаса в 60 с
    assert await auth.get_token() == "t2"
    assert oauth.call_count == 2


@respx.mock
async def test_parallel_requests_fetch_token_once(http, clock):
    oauth = respx.post(AUTH_URL).mock(return_value=token_response(clock=clock))
    respx.post(f"{BASE}/chat/completions").mock(return_value=chat_ok())
    _, llm, _ = make(http, clock)
    await asyncio.gather(*(llm.complete([Message("user", "x")]) for _ in range(5)))
    assert oauth.call_count == 1


@respx.mock
async def test_complete_parses_response_and_sends_payload(http, clock):
    respx.post(AUTH_URL).mock(return_value=token_response(clock=clock))
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=chat_ok("ответ"))
    _, llm, _ = make(http, clock)
    res = await llm.complete(
        [Message("system", "s"), Message("user", "q")], temperature=0.1, max_tokens=50
    )
    assert (res.text, res.provider, res.prompt_tokens, res.completion_tokens) == (
        "ответ", "gigachat", 3, 1,
    )
    sent = json.loads(route.calls[0].request.content)
    assert sent == {
        "model": "GigaChat",
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}],
        "stream": False,
        "temperature": 0.1,
        "max_tokens": 50,
    }
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok-1"


@respx.mock
async def test_401_refreshes_token_once(http, clock):
    respx.post(AUTH_URL).mock(
        side_effect=[token_response("old", clock=clock), token_response("new", clock=clock)]
    )
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[httpx.Response(401), chat_ok()]
    )
    _, llm, _ = make(http, clock)
    assert (await llm.complete([Message("user", "x")])).text == "привет"
    assert route.calls[1].request.headers["Authorization"] == "Bearer new"


@respx.mock
async def test_persistent_401_raises_auth_error(http, clock):
    respx.post(AUTH_URL).mock(return_value=token_response(clock=clock))
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(401))
    _, llm, _ = make(http, clock)
    with pytest.raises(LLMAuthError):
        await llm.complete([Message("user", "x")])


@respx.mock
async def test_bad_credentials_raise_auth_error(http, clock):
    respx.post(AUTH_URL).mock(return_value=httpx.Response(401))
    _, llm, _ = make(http, clock)
    with pytest.raises(LLMAuthError) as e:
        await llm.complete([Message("user", "x")])
    assert e.value.retryable is False  # fallback при ошибке ключей не включается


@respx.mock
async def test_retries_on_5xx_then_succeeds(http, clock):
    respx.post(AUTH_URL).mock(return_value=token_response(clock=clock))
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[httpx.Response(503), httpx.Response(429), chat_ok()]
    )
    _, llm, _ = make(http, clock)
    assert (await llm.complete([Message("user", "x")])).text == "привет"
    assert route.call_count == 3


@respx.mock
async def test_gives_up_with_unavailable(http, clock):
    respx.post(AUTH_URL).mock(return_value=token_response(clock=clock))
    route = respx.post(f"{BASE}/chat/completions").mock(side_effect=httpx.ConnectTimeout("t"))
    _, llm, _ = make(http, clock)
    with pytest.raises(LLMUnavailableError) as e:
        await llm.complete([Message("user", "x")])
    assert e.value.retryable is True
    assert route.call_count == 3  # 1 + 2 повтора


@respx.mock
async def test_malformed_response(http, clock):
    respx.post(AUTH_URL).mock(return_value=token_response(clock=clock))
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(200, json={"x": 1}))
    _, llm, _ = make(http, clock)
    with pytest.raises(LLMResponseError):
        await llm.complete([Message("user", "x")])


@respx.mock
async def test_error_messages_do_not_leak_secrets(http, clock):
    respx.post(AUTH_URL).mock(return_value=httpx.Response(401, text="KEY== secret body"))
    _, llm, _ = make(http, clock)
    with pytest.raises(LLMAuthError) as e:
        await llm.complete([Message("user", "x")])
    assert "KEY==" not in e.value.message and "secret" not in e.value.message


def sse(*events):
    lines = [f"data: {json.dumps(e, ensure_ascii=False)}\n" for e in events] + ["data: [DONE]\n"]
    return httpx.Response(200, content="\n".join(lines).encode(),
                          headers={"content-type": "text/event-stream"})


@respx.mock
async def test_stream_yields_deltas(http, clock):
    respx.post(AUTH_URL).mock(return_value=token_response(clock=clock))
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=sse(
            {"choices": [{"delta": {"role": "assistant", "content": "При"}}]},
            {"choices": [{"delta": {"content": "вет"}}]},
            {"choices": [{"delta": {}}]},
        )
    )
    _, llm, _ = make(http, clock)
    chunks = [c async for c in llm.stream([Message("user", "x")])]
    assert chunks == ["При", "вет"]
    assert json.loads(route.calls[0].request.content)["stream"] is True


@respx.mock
async def test_stream_retries_before_first_chunk(http, clock):
    respx.post(AUTH_URL).mock(return_value=token_response(clock=clock))
    respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[httpx.Response(503), sse({"choices": [{"delta": {"content": "ok"}}]})]
    )
    _, llm, _ = make(http, clock)
    assert [c async for c in llm.stream([Message("user", "x")])] == ["ok"]


@respx.mock
async def test_stream_auth_error(http, clock):
    respx.post(AUTH_URL).mock(return_value=token_response(clock=clock))
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(403))
    _, llm, _ = make(http, clock)
    with pytest.raises(LLMAuthError):
        [c async for c in llm.stream([Message("user", "x")])]


def emb_handler(request):
    inputs = json.loads(request.content)["input"]
    # Намеренно в обратном порядке: адаптер должен упорядочить по index.
    data = [{"index": i, "embedding": [float(len(t))] * DIM} for i, t in enumerate(inputs)]
    return httpx.Response(200, json={"data": list(reversed(data))})


@respx.mock
async def test_embeddings_batching_and_order(http, clock):
    respx.post(AUTH_URL).mock(return_value=token_response(clock=clock))
    route = respx.post(f"{BASE}/embeddings").mock(side_effect=emb_handler)
    _, _, emb = make(http, clock)
    texts = ["a", "bb", "ccc", "dddd", "eeeee"]
    vectors = await emb.embed(texts)
    assert route.call_count == 3  # пакеты по 2
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert json.loads(route.calls[0].request.content)["model"] == "Embeddings"
    assert await emb.embed([]) == []


@respx.mock
async def test_embeddings_dimension_mismatch(http, clock):
    respx.post(AUTH_URL).mock(return_value=token_response(clock=clock))
    respx.post(f"{BASE}/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
    )
    _, _, emb = make(http, clock)
    with pytest.raises(LLMResponseError):
        await emb.embed(["a"])


@respx.mock
async def test_embeddings_retry_on_503(http, clock):
    respx.post(AUTH_URL).mock(return_value=token_response(clock=clock))
    route = respx.post(f"{BASE}/embeddings").mock(
        side_effect=[httpx.Response(503), emb_handler]
    )
    _, _, emb = make(http, clock)
    assert len(await emb.embed(["a"])) == 1
    assert route.call_count == 2


@pytest.mark.parametrize("bundle", ["", "/nonexistent/ca.pem"])
def test_ssl_context_trusts_russian_ca_without_bundle(bundle):
    ctx = make_ssl_context(SimpleNamespace(gigachat_ca_bundle=bundle))
    names = {
        dict(x[0] for x in cert["subject"]).get("commonName") for cert in ctx.get_ca_certs()
    }
    assert {"Russian Trusted Root CA", "Russian Trusted Sub CA"} <= names
    assert len(names) > 2  # certifi тоже на месте: Cloud.ru и прочие хосты не сломаются
