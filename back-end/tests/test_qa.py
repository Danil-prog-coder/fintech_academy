from tests.conftest import register, set_repo_status

URL = "https://github.com/acme/project"


async def _ready_user(client, email="user@example.com"):
    h = await register(client, email)
    await client.post("/repo/connect", json={"url": URL}, headers=h)
    await set_repo_status("ready", "abc123")
    return h


async def test_ask_requires_repo(client):
    h = await register(client)
    r = await client.post("/qa/ask", json={"question": "Как деплоить?"}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "repo_not_connected"


async def test_ask_blocked_while_indexing(client):
    h = await register(client)
    await client.post("/repo/connect", json={"url": URL}, headers=h)
    r = await client.post("/qa/ask", json={"question": "Как деплоить?"}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "index_not_ready"
    assert r.json()["retryable"] is True


async def test_ask_not_found_and_conversation_history(client):
    h = await _ready_user(client)
    r = await client.post("/qa/ask", json={"question": "Как деплоить?"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not_found" and body["sources"] == []
    assert body["index_commit"] == "abc123"

    r2 = await client.post(
        "/qa/ask",
        json={"question": "А где конфиг?", "conversation_id": body["conversation_id"]},
        headers=h,
    )
    assert r2.json()["conversation_id"] == body["conversation_id"]

    conv = await client.get(f"/qa/conversations/{body['conversation_id']}", headers=h)
    assert [m["role"] for m in conv.json()["messages"]] == ["user", "assistant"] * 2


async def test_conversation_isolated_between_users(client):
    h1 = await _ready_user(client)
    r = await client.post("/qa/ask", json={"question": "Вопрос?"}, headers=h1)
    cid = r.json()["conversation_id"]
    h2 = await register(client, "other@example.com")
    assert (await client.get(f"/qa/conversations/{cid}", headers=h2)).status_code == 404
    again = await client.post(
        "/qa/ask", json={"question": "Чужой?", "conversation_id": cid}, headers=h2
    )
    assert again.status_code in (404, 409)


async def test_ask_stream_sse(client):
    h = await _ready_user(client)
    r = await client.post("/qa/ask", json={"question": "Вопрос?", "stream": True}, headers=h)
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "event: status" in r.text and "event: answer" in r.text and "event: done" in r.text


async def test_ask_validation(client):
    h = await _ready_user(client)
    r = await client.post("/qa/ask", json={"question": ""}, headers=h)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


async def test_unknown_source_404(client):
    h = await register(client)
    assert (await client.get("/sources/1", headers=h)).status_code == 404
