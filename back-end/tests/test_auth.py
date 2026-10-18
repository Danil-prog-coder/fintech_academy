CREDS = {"email": "User@Example.com", "password": "correct-horse"}


async def _register(client, creds=CREDS):
    r = await client.post("/auth/register", json=creds)
    assert r.status_code == 201
    return r.json()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


async def test_register_login_me(client):
    await _register(client)
    r = await client.post("/auth/login", json=CREDS)
    assert r.status_code == 200
    me = await client.get("/me", headers=_h(r.json()["access_token"]))
    assert me.json()["email"] == "user@example.com"


async def test_duplicate_email_case_insensitive(client):
    await _register(client)
    r = await client.post("/auth/register", json={**CREDS, "email": "user@example.COM"})
    assert r.status_code == 409
    assert r.json() == {
        "code": "email_taken",
        "message": "Пользователь с таким email уже существует.",
        "retryable": False,
    }


async def test_wrong_password(client):
    await _register(client)
    r = await client.post("/auth/login", json={**CREDS, "password": "wrong-password"})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


async def test_short_password_validation_format(client):
    r = await client.post("/auth/register", json={**CREDS, "password": "short"})
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


async def test_refresh_and_token_kinds(client):
    tokens = await _register(client)
    r = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    # access-токен нельзя использовать как refresh и наоборот
    bad = await client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert bad.status_code == 401
    assert (await client.get("/me", headers=_h(tokens["refresh_token"]))).status_code == 401


async def test_me_requires_auth(client):
    assert (await client.get("/me")).status_code == 401


async def test_api_token_lifecycle(client):
    tokens = await _register(client)
    created = await client.post(
        "/auth/api-tokens", json={"name": "chrome"}, headers=_h(tokens["access_token"])
    )
    assert created.status_code == 201
    raw = created.json()["token"]
    assert (await client.get("/me", headers=_h(raw))).status_code == 200

    rev = await client.delete(
        f"/auth/api-tokens/{created.json()['id']}", headers=_h(tokens["access_token"])
    )
    assert rev.status_code == 204
    assert (await client.get("/me", headers=_h(raw))).status_code == 401


async def test_cannot_revoke_foreign_token(client):
    a = await _register(client)
    b = await _register(client, {"email": "b@example.com", "password": "another-pass1"})
    created = await client.post(
        "/auth/api-tokens", json={"name": "x"}, headers=_h(a["access_token"])
    )
    r = await client.delete(
        f"/auth/api-tokens/{created.json()['id']}", headers=_h(b["access_token"])
    )
    assert r.status_code == 404
