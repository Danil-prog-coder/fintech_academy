from sqlalchemy import select

from app.db import session as db_session
from app.db.models import Job, Repository
from tests.conftest import register

URL = "https://github.com/acme/project"


async def test_status_when_not_connected(client):
    h = await register(client)
    r = await client.get("/repo/status", headers=h)
    assert r.json()["status"] == "not_connected"
    assert (await client.get("/me", headers=h)).json()["repo_status"] == "not_connected"


async def test_connect_creates_index_job_and_encrypts_token(client):
    h = await register(client)
    r = await client.post("/repo/connect", json={"url": URL + ".git", "github_token": "ghp_x"}, headers=h)
    assert r.status_code == 201
    body = r.json()
    assert (body["status"], body["owner"], body["name"]) == ("indexing", "acme", "project")
    assert "ghp_x" not in r.text

    async with db_session._sessionmaker() as s:
        repo = await s.scalar(select(Repository))
        assert repo.github_token_encrypted and "ghp_x" not in repo.github_token_encrypted
        job = await s.scalar(select(Job))
        assert job.type == "index_full" and job.repo_id == repo.id
    assert (await client.get("/me", headers=h)).json()["repo_status"] == "indexing"


async def test_connect_validation_and_access_errors(client):
    h = await register(client)
    bad_url = await client.post("/repo/connect", json={"url": "https://gitlab.com/a/b"}, headers=h)
    assert bad_url.status_code == 422 and bad_url.json()["code"] == "invalid_repo_url"
    no_access = await client.post(
        "/repo/connect", json={"url": URL, "github_token": "bad"}, headers=h
    )
    assert no_access.status_code == 400 and no_access.json()["code"] == "repo_no_access"


async def test_replace_requires_confirmation(client):
    h = await register(client)
    await client.post("/repo/connect", json={"url": URL}, headers=h)
    again = await client.post("/repo/connect", json={"url": "https://github.com/acme/other"}, headers=h)
    assert again.status_code == 409 and again.json()["code"] == "repo_exists"
    ok = await client.post(
        "/repo/connect", json={"url": "https://github.com/acme/other", "replace": True}, headers=h
    )
    assert ok.status_code == 201 and ok.json()["name"] == "other"
    async with db_session._sessionmaker() as s:
        assert len((await s.scalars(select(Repository))).all()) == 1
        assert len((await s.scalars(select(Job))).all()) == 1


async def test_disconnect(client):
    h = await register(client)
    assert (await client.delete("/repo", headers=h)).status_code == 404
    await client.post("/repo/connect", json={"url": URL}, headers=h)
    assert (await client.delete("/repo", headers=h)).status_code == 204
    assert (await client.get("/repo/status", headers=h)).json()["status"] == "not_connected"


async def test_repo_endpoints_require_auth(client):
    assert (await client.post("/repo/connect", json={"url": URL})).status_code == 401
    assert (await client.get("/repo/status")).status_code == 401
