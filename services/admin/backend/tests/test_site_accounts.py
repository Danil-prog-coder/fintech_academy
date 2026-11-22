"""The site on its own: register → create a project (or join one as an admin with its code) → work in it."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.conftest import CSRF, PW, create_project, new_client, panel_login, register, set_password


async def test_register_validates_and_keeps_logins_unique(env):
    me = await register(env.client, "Olga.Owner")
    assert me == {"login": "olga.owner", "project": None, "role": None, "display_name": None, "external_id": None}
    async with new_client(env) as other:
        r = await other.post("/panel/api/auth/register", headers=CSRF, json={"login": "olga.owner", "password": PW})
        assert r.status_code == 409 and r.json()["code"] == "login_taken"
        r = await other.post("/panel/api/auth/register", headers=CSRF, json={"login": "x", "password": PW})
        assert r.json()["code"] == "bad_login"
        r = await other.post("/panel/api/auth/register", headers=CSRF, json={"login": "anna", "password": ""})
        assert r.json()["code"] == "empty_password"
        # no rules on length or complexity: «1» is a password
        r = await other.post("/panel/api/auth/register", headers=CSRF, json={"login": "anna", "password": "1"})
        assert r.status_code == 201, r.text
        assert (await other.post("/panel/api/auth/login", json={"login": "anna", "password": "1"})).status_code == 200
    # signed in at once, but without a project the panel pages are closed
    r = await env.client.get("/panel/api/stats")
    assert r.status_code == 409 and r.json()["code"] == "project_not_selected"


async def test_create_project_on_the_site_and_join_as_admin_with_the_code(env):
    await register(env.client, "olga")
    r = await env.client.post("/panel/api/projects", headers=CSRF, json={"name": "  Отдел   кадров "})
    assert r.status_code == 201, r.text
    created = r.json()
    pid, code = created["project"]["id"], created["project_code"]
    assert created["role"] == "owner" and created["project"]["name"] == "Отдел кадров" and code.startswith(pid + "-")
    assert (await env.client.get("/panel/api/project/code")).json()["code"] == code
    # the project lives in an integration (the oldest one by default): its users will ask the questions
    v1 = (await env.client.get(f"/v1/projects/{pid}/members", headers=env.h)).json()["members"]
    assert [(m["external_id"], m["role"], m["panel_login"], m["panel_password_set"]) for m in v1] == [
        ("site:1", "owner", "olga", True)]
    assert (await env.client.get(f"/v1/projects/{pid}", headers=env.hb)).status_code == 404

    async with new_client(env) as helper:
        await register(helper, "pavel")
        r = await helper.post("/panel/api/projects/join", headers=CSRF, json={"project_code": code[:-1] + "x"})
        assert r.status_code == 403 and r.json()["code"] == "bad_project_code"
        r = await helper.post("/panel/api/projects/join", headers=CSRF, json={"project_code": code})
        assert r.status_code == 200 and r.json()["role"] == "admin" and r.json()["project"]["id"] == pid
        # an admin works with documentation but not with the owner's settings
        assert (await helper.get("/panel/api/documents")).status_code == 200
        assert (await helper.get("/panel/api/project/code")).status_code == 403
        # joining again changes nothing
        r = await helper.post("/panel/api/projects/join", headers=CSRF, json={"project_code": code})
        assert r.json()["role"] == "admin"
        assert [p["role"] for p in (await helper.get("/panel/api/projects")).json()["projects"]] == ["admin"]

        # the owner takes the admin rights away: the code does not give them back
        r = await env.client.patch("/panel/api/members/site:2", headers=CSRF, json={"role": "user"})
        assert r.status_code == 200, r.text
        assert (await helper.get("/panel/api/me")).json()["project"] is None
        r = await helper.post("/panel/api/projects/join", headers=CSRF, json={"project_code": code})
        assert r.status_code == 403 and r.json()["code"] == "status_by_owner"

        # a new code: the old one stops opening the project
        new_code = (await env.client.post("/panel/api/project/code/rotate", headers=CSRF)).json()["code"]
        await register(helper, "kira")
        r = await helper.post("/panel/api/projects/join", headers=CSRF, json={"project_code": code})
        assert r.status_code == 403
        r = await helper.post("/panel/api/projects/join", headers=CSRF, json={"project_code": new_code})
        assert r.json()["role"] == "admin"


async def test_one_account_many_projects_and_the_picker(env):
    await register(env.client, "olga")
    first = (await env.client.post("/panel/api/projects", headers=CSRF, json={"name": "Первый"})).json()["project"]["id"]
    second = (await env.client.post("/panel/api/projects", headers=CSRF, json={"name": "Второй"})).json()["project"]["id"]
    items = (await env.client.get("/panel/api/projects")).json()["projects"]
    assert [(p["id"], p["role"], p["current"]) for p in items] == [(first, "owner", False), (second, "owner", True)]
    r = await env.client.post(f"/panel/api/projects/{first}/select", headers=CSRF)
    assert r.json()["project"]["id"] == first
    assert (await env.client.get("/panel/api/project")).json()["id"] == first
    # several projects: a new sign-in starts at the picker
    async with new_client(env) as again:
        me = (await again.post("/panel/api/auth/login", json={"login": "olga", "password": PW})).json()
        assert me["project"] is None
        assert (await again.post(f"/panel/api/projects/{second}/select")).status_code == 403  # CSRF header
        assert (await again.post("/panel/api/projects/ffffffff/select", headers=CSRF)).status_code == 404


async def test_access_from_an_integration_is_attached_to_an_existing_account(env):
    data = await create_project(env)
    pid = data["project"]["id"]
    await register(env.client, "olga")
    mine = (await env.client.post("/panel/api/projects", headers=CSRF, json={"name": "Свой"})).json()["project"]["id"]
    token = data["owner_panel_setup_url"].split("=", 1)[1]
    async with new_client(env) as anonymous:
        assert (await anonymous.post("/panel/api/auth/claim", headers=CSRF, json={"token": token})).status_code == 401
    r = await env.client.post("/panel/api/auth/claim", headers=CSRF, json={"token": token})
    assert r.status_code == 200 and r.json()["project"]["id"] == pid and r.json()["role"] == "owner"
    assert {p["id"] for p in (await env.client.get("/panel/api/projects")).json()["projects"]} == {pid, mine}
    # one account cannot hold two accesses to one project
    r = await env.client.put(f"/v1/projects/{pid}/members/u-admin", headers=env.h,
                             json={"acting_external_id": "u-owner", "role": "admin", "login": "admin1"})
    token2 = r.json()["panel_setup_url"].split("=", 1)[1]
    r = await env.client.post("/panel/api/auth/claim", headers=CSRF, json={"token": token2})
    assert r.status_code == 409 and r.json()["code"] == "already_in_project"


async def test_owner_link_moves_lost_access_to_a_new_account(env):
    data = await create_project(env)
    pid = data["project"]["id"]
    r = await env.client.put(f"/v1/projects/{pid}/members/u-admin", headers=env.h,
                             json={"acting_external_id": "u-owner", "role": "admin", "login": "admin1"})
    pw = await set_password(env, r.json()["panel_setup_url"])
    async with new_client(env) as old:
        await panel_login(env, "admin1", pw, client=old)
        r = await env.client.post(f"/v1/projects/{pid}/members/u-admin/panel-password-reset", headers=env.h,
                                  json={"acting_external_id": "u-owner"})
        await set_password(env, r.json()["panel_setup_url"], login="admin1-new")
        assert (await old.get("/panel/api/me")).json()["project"] is None
    members = {m["external_id"]: m for m in (await env.client.get(f"/v1/projects/{pid}/members", headers=env.h)).json()["members"]}
    assert members["u-admin"]["panel_login"] == "admin1-new"


async def test_integration_user_joins_as_admin_with_the_code(env):
    data = await create_project(env)
    pid, code = data["project"]["id"], data["project_code"]
    join = lambda h, body: env.client.post("/v1/projects/join", headers=h, json=body)  # noqa: E731
    r = await join(env.h, {"external_id": "u-5", "project_code": "garbage"})
    assert r.status_code == 403 and r.json()["code"] == "bad_project_code"
    # another integration's project is closed even with the right code
    r = await join(env.hb, {"external_id": "u-5", "project_code": code})
    assert r.status_code == 403 and r.json()["code"] == "bad_project_code"
    r = await join(env.h, {"external_id": "u-5", "project_code": code, "login": "anna@mail.test", "display_name": "Анна"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project"]["role"] == "admin" and body["member"]["panel_login"] == "anna@mail.test"
    assert body["panel_setup_url"].startswith("https://panel.test/setup?token=")
    # an admin adds users at once
    r = await env.client.put(f"/v1/projects/{pid}/members/u-6", headers=env.h, json={"acting_external_id": "u-5", "role": "user"})
    assert r.status_code == 200
    # a plain user does not become an admin with the code; the owner stays the owner
    assert (await join(env.h, {"external_id": "u-6", "project_code": code})).json()["code"] == "status_by_owner"
    assert (await join(env.h, {"external_id": "u-owner", "project_code": code})).json()["project"]["role"] == "owner"


def test_migration_moves_existing_passwords_into_site_accounts(tmp_path):
    """0001 → 0002 on a database with panel accounts from before: logins and passwords keep working."""
    db_file = tmp_path / "m.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_file}"}
    root = Path(__file__).resolve().parents[1]
    run = lambda rev: subprocess.run([sys.executable, "-m", "alembic", "upgrade", rev], cwd=root, env=env,  # noqa: E731
                                     capture_output=True, text=True, check=True)
    run("0001")
    con = sqlite3.connect(db_file)
    now = "2026-11-01 10:00:00"
    con.execute("INSERT INTO integrations (id, slug, name, key_hash, key_prefix, created_at) VALUES (1,'m','M','h','p',?)", (now,))
    for pid in (1, 2):
        con.execute("INSERT INTO projects (id, public_id, integration_id, name, code_hash, code_enc, code_issued_at, created_at) "
                    "VALUES (?, ?, 1, 'P', 'h', 'e', ?, ?)", (pid, f"0000000{pid}", now, now))
    rows = [(1, 1, "olga", "hash-1"), (2, 1, "pavel", None), (3, 2, "olga", "hash-3")]
    for aid, pid, login, pw_hash in rows:
        con.execute("INSERT INTO members (id, project_id, external_id, role, created_at, updated_at) VALUES (?, ?, ?, 'admin', ?, ?)",
                    (aid, pid, f"u{aid}", now, now))
        con.execute("INSERT INTO panel_accounts (id, project_id, member_id, login, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (aid, pid, aid, login, pw_hash, now))
    con.execute("INSERT INTO panel_sessions (token_hash, account_id, created_at, expires_at) VALUES ('t', 1, ?, ?)", (now, now))
    con.commit()
    con.close()
    run("head")
    con = sqlite3.connect(db_file)
    assert con.execute("SELECT login, password_hash FROM site_users").fetchall() == [("olga", "hash-1")]
    assert con.execute("SELECT id, user_id FROM panel_accounts ORDER BY id").fetchall() == [(1, 1), (2, None), (3, None)]
    assert con.execute("SELECT count(*) FROM panel_sessions").fetchone() == (0,)
    con.close()
