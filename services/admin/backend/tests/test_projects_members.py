import httpx

from tests.conftest import create_project, panel_login, set_password


async def test_create_project_returns_code_once_and_owner_can_log_in(env):
    data = await create_project(env)
    pid, code = data["project"]["id"], data["project_code"]
    assert data["project"]["role"] == "owner" and code.startswith(pid + "-")
    assert data["owner_panel_setup_url"].startswith("https://panel.test/setup?token=")
    pw = await set_password(env, data["owner_panel_setup_url"])
    # the link is single-use
    r = await env.client.post("/panel/api/auth/setup", json={"token": data["owner_panel_setup_url"].split("=")[1], "password": pw})
    assert r.status_code == 410
    await panel_login(env, "owner", pw, code)
    me = (await env.client.get("/panel/api/me")).json()
    assert me == {"login": "owner", "role": "owner", "display_name": "Оля", "external_id": "u-owner",
                  "project": {"id": pid, "name": "Проект X"}}
    # the owner sees the code in the panel at any time
    assert (await env.client.get("/panel/api/project/code")).json()["code"] == code


async def test_login_needs_all_three_and_says_the_same_on_any_mistake(env):
    data = await create_project(env)
    pw = await set_password(env, data["owner_panel_setup_url"])
    code = data["project_code"]
    bad = [("owner", "wrong-password-123", code), ("nobody", pw, code), ("owner", pw, code[:-1] + "x"), ("owner", pw, "garbage")]
    for login, password, c in bad:
        r = await env.client.post("/panel/api/auth/login", json={"login": login, "password": password, "project_code": c})
        assert r.status_code == 401 and r.json()["message"] == "Неверный логин, пароль или код проекта"


async def test_login_attempts_are_limited(env):
    data = await create_project(env)
    for _ in range(env.settings.login_attempts):
        await env.client.post("/panel/api/auth/login", json={"login": "owner", "password": "x" * 12, "project_code": data["project_code"]})
    r = await env.client.post("/panel/api/auth/login", json={"login": "owner", "password": "x" * 12, "project_code": data["project_code"]})
    assert r.status_code == 429


async def test_api_key_is_required_and_projects_are_isolated_between_integrations(env):
    assert (await env.client.get("/v1/projects")).status_code == 401
    assert (await env.client.get("/v1/projects", headers={"X-Api-Key": "nope"})).status_code == 401
    pid = (await create_project(env))["project"]["id"]
    assert (await env.client.get(f"/v1/projects/{pid}", headers=env.h)).status_code == 200
    r = await env.client.get(f"/v1/projects/{pid}", headers=env.hb)
    assert r.status_code == 404 and r.json()["code"] == "project_not_found"


async def test_owner_registers_ids_with_statuses(env):
    data = await create_project(env)
    pid = data["project"]["id"]
    put = lambda ext, body: env.client.put(f"/v1/projects/{pid}/members/{ext}", headers=env.h, json=body)  # noqa: E731
    # admin and support need a login: they will use the site
    r = await put("u-admin", {"acting_external_id": "u-owner", "role": "admin"})
    assert r.status_code == 400 and r.json()["code"] == "login_required"
    r = await put("u-admin", {"acting_external_id": "u-owner", "role": "admin", "login": "admin1"})
    assert r.status_code == 200 and r.json()["panel_setup_url"]
    r = await put("u-sup", {"acting_external_id": "u-owner", "role": "support", "login": "sup1"})
    assert r.json()["member"]["role"] == "support"
    r = await put("u-1", {"acting_external_id": "u-owner", "role": "user"})
    assert r.json()["member"] == {**r.json()["member"], "role": "user", "panel_login": None}
    assert "panel_setup_url" not in r.json()
    members = (await env.client.get(f"/v1/projects/{pid}/members", headers=env.h)).json()["members"]
    assert {m["external_id"]: m["role"] for m in members} == {"u-owner": "owner", "u-admin": "admin", "u-sup": "support", "u-1": "user"}
    projects_of_user = (await env.client.get("/v1/projects", headers=env.h, params={"external_id": "u-1"})).json()["projects"]
    assert projects_of_user == [{"id": pid, "name": "Проект X", "created_at": projects_of_user[0]["created_at"], "role": "user"}]


async def test_status_rules(env):
    data = await create_project(env)
    pid = data["project"]["id"]

    async def put(acting, ext, role, **extra):
        return await env.client.put(f"/v1/projects/{pid}/members/{ext}", headers=env.h,
                                    json={"acting_external_id": acting, "role": role, **extra})

    await put("u-owner", "u-admin", "admin", login="admin1")
    await put("u-owner", "u-sup", "support", login="sup1")
    # an admin manages users only
    assert (await put("u-admin", "u-2", "user")).status_code == 200
    r = await put("u-admin", "u-3", "support", login="sup3")
    assert r.status_code == 403 and r.json()["code"] == "owner_only"
    assert (await put("u-admin", "u-sup", "user")).status_code == 403
    # nobody changes himself, nobody touches the owner, outsiders and support cannot manage
    assert (await put("u-admin", "u-admin", "user")).json()["code"] == "cannot_change_self"
    assert (await put("u-admin", "u-owner", "user")).json()["code"] == "owner_is_fixed"
    assert (await put("u-sup", "u-9", "user")).json()["code"] == "not_a_manager"
    assert (await put("stranger", "u-9", "user")).json()["code"] == "not_a_member"
    assert (await put("u-owner", "u-9", "owner")).status_code == 422  # «owner» is not an assignable status
    # removal
    rm = lambda acting, ext: env.client.delete(f"/v1/projects/{pid}/members/{ext}", headers=env.h,  # noqa: E731
                                               params={"acting_external_id": acting})
    assert (await rm("u-admin", "u-sup")).status_code == 403
    assert (await rm("u-admin", "u-2")).status_code == 204
    assert (await rm("u-owner", "u-owner")).status_code == 403
    assert (await rm("u-owner", "u-sup")).status_code == 204


async def test_demoted_admin_loses_the_site(env):
    data = await create_project(env)
    pid, code = data["project"]["id"], data["project_code"]
    r = await env.client.put(f"/v1/projects/{pid}/members/u-admin", headers=env.h,
                             json={"acting_external_id": "u-owner", "role": "admin", "login": "admin1"})
    pw = await set_password(env, r.json()["panel_setup_url"])
    admin = httpx.AsyncClient(transport=env.client._transport, base_url="https://api.test")
    r = await admin.post("/panel/api/auth/login", json={"login": "admin1", "password": pw, "project_code": code})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    await env.client.put(f"/v1/projects/{pid}/members/u-admin", headers=env.h, json={"acting_external_id": "u-owner", "role": "user"})
    assert (await admin.get("/panel/api/me")).status_code == 401
    r = await admin.post("/panel/api/auth/login", json={"login": "admin1", "password": pw, "project_code": code})
    assert r.status_code == 401
    await admin.aclose()


async def test_sections_restrict_users_but_not_managers(env):
    data = await create_project(env)
    pid, code = data["project"]["id"], data["project_code"]
    pw = await set_password(env, data["owner_panel_setup_url"])
    h = await panel_login(env, "owner", pw, code)
    assert (await env.client.post("/panel/api/sections", headers=h, json={"slug": "security", "title": "Безопасность"})).status_code == 201
    r = await env.client.put(f"/v1/projects/{pid}/members/u-1", headers=env.h,
                             json={"acting_external_id": "u-owner", "role": "user", "allowed_sections": ["nope"]})
    assert r.json()["code"] == "unknown_section"
    await env.client.put(f"/v1/projects/{pid}/members/u-1", headers=env.h,
                         json={"acting_external_id": "u-owner", "role": "user", "allowed_sections": ["general"]})
    await env.client.post(f"/v1/projects/{pid}/ask", headers=env.h, json={"external_id": "u-1", "message": "Где ключи?"})
    await env.client.post(f"/v1/projects/{pid}/ask", headers=env.h, json={"external_id": "u-owner", "message": "Где ключи?"})
    asks = [c[2] for c in env.rag.calls if c[1] == "/ask/sync"]
    assert asks[0]["allowed_sections"] == ["general"] and asks[1]["allowed_sections"] is None
    # keep_sections: a status update without sections keeps the restriction
    r = await env.client.put(f"/v1/projects/{pid}/members/u-1", headers=env.h,
                             json={"acting_external_id": "u-owner", "role": "user", "display_name": "Ваня"})
    assert r.json()["member"]["allowed_sections"] == ["general"]


async def test_panel_requires_csrf_header_and_role(env):
    data = await create_project(env)
    pid, code = data["project"]["id"], data["project_code"]
    r = await env.client.put(f"/v1/projects/{pid}/members/u-sup", headers=env.h,
                             json={"acting_external_id": "u-owner", "role": "support", "login": "sup1"})
    pw = await set_password(env, r.json()["panel_setup_url"])
    h = await panel_login(env, "sup1", pw, code)
    assert (await env.client.get("/panel/api/documents")).status_code == 403
    assert (await env.client.get("/panel/api/escalations")).status_code == 200
    assert (await env.client.post("/panel/api/auth/logout")).status_code == 403  # no X-Requested-With
    assert (await env.client.post("/panel/api/auth/logout", headers=h)).status_code == 204
    assert (await env.client.get("/panel/api/me")).status_code == 401


async def test_health_reports_database_and_rag(env):
    body = (await env.client.get("/health")).json()
    assert body == {"status": "ok", "version": body["version"], "database": "ok", "rag": "ok"}
