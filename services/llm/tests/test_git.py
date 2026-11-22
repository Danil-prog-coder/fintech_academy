"""Git repository as a knowledge source (FR-GIT-01..05, 07) with a fake provider (no network)."""

import hashlib
import hmac
import uuid

import pytest

import rag_service.ingest.pipeline as pipeline
from rag_service.config import get_settings
from rag_service.git_source import sources
from rag_service.git_source.providers import Change, GitHubProvider, GitLabProvider, RepoFile, heading_anchor
from rag_service.index import store
from tests.fakes import FakeEmbedder


def test_glob_matching():
    inc, exc = ["docs/**/*.md", "*.md"], ["docs/drafts/**"]
    assert sources.matches("docs/a/b.md", inc, exc)
    assert sources.matches("docs/b.md", inc, exc)
    assert sources.matches("README.md", inc, exc)
    assert not sources.matches("docs/drafts/x.md", inc, exc)
    assert not sources.matches("src/x.md", inc, exc)


def test_blob_urls_pinned_to_commit_with_anchor():
    gh = GitHubProvider("org/kb", "main")
    assert gh.blob_url("abc123", "docs/Реестр мебели.md", anchor="статусы") == \
        "https://github.com/org/kb/blob/abc123/docs/%D0%A0%D0%B5%D0%B5%D1%81%D1%82%D1%80%20%D0%BC%D0%B5%D0%B1%D0%B5%D0%BB%D0%B8.md#статусы"
    gl = GitLabProvider("grp/kb", "main", base_url="https://git.local")
    assert gl.blob_url("abc", "a.md", lines=(3, 9)).startswith("https://git.local/grp/kb/-/blob/abc/a.md#L3")
    assert heading_anchor("4. Согласование заявки!") == "4-согласование-заявки"


def test_webhook_signatures():
    body = b'{"ref":"refs/heads/main"}'
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert sources.verify_github("s3cret", body, sig)
    assert not sources.verify_github("s3cret", body + b" ", sig)
    assert not sources.verify_github("s3cret", body, None)
    assert sources.verify_gitlab("tok", "tok") and not sources.verify_gitlab("tok", "bad")


def test_plan_changes_incremental():
    src = {"include": ["**/*.md"], "exclude": [], "files": {"a.md": {}, "b.md": {}, "old.md": {}}}
    tree = {"a.md": 10, "b.md": 10, "new.md": 10, "img.png": 5}
    changes = [Change("modified", "a.md"), Change("renamed", "new.md", "old.md")]
    to_index, to_remove, skipped = sources.plan_changes(src, tree, changes)
    assert to_index == {"a.md", "new.md"} and to_remove == {"old.md"} and not skipped
    # full import: everything matching
    to_index, to_remove, _ = sources.plan_changes(src, tree, None)
    assert to_index == {"a.md", "b.md", "new.md"} and to_remove == {"old.md"}


def test_plan_changes_size_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "git_max_file_bytes", 100)
    _, _, skipped = sources.plan_changes({"include": ["**/*.md"], "exclude": [], "files": {}}, {"big.md": 1000}, None)
    assert skipped and "лимита" in skipped[0]["why"]


def test_token_env_must_be_a_name(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "state_dir", str(tmp_path))
    with pytest.raises(ValueError):
        sources.add("p", "github", "org/kb", token_env="ghp_actualtokenvalue")
    src = sources.add("p", "github", "org/kb", token_env="KB_GIT_TOKEN")
    assert "webhook_secret" not in sources.public_view(src)


class FakeRepo:
    name = "github"

    def __init__(self):
        self.commits = {"c1": {"docs/a.md": "# Заявка\n\n## Согласование\n\nЗаявку согласует руководитель отдела.\n",
                               "docs/b.md": "# Отпуск\n\n## Оформление\n\nОтпуск оформляется в разделе Кадры.\n",
                               "src/main.py": "print(1)\n"}}
        self.head_sha = "c1"
        self.fetched: list[str] = []

    def commit(self, sha, files):
        self.commits[sha] = files
        self.head_sha = sha

    def head(self):
        return self.head_sha

    def list_files(self, sha):
        return [RepoFile(p, len(t.encode()), hashlib.sha1(t.encode()).hexdigest()) for p, t in self.commits[sha].items()]

    def fetch(self, sha, path):
        self.fetched.append(path)
        return self.commits[sha][path].encode()

    def compare(self, base, head):
        a, b = self.commits[base], self.commits[head]
        out = [Change("added", p) for p in b if p not in a] + [Change("removed", p) for p in a if p not in b]
        return out + [Change("modified", p) for p in b if p in a and a[p] != b[p]]

    def blob_url(self, sha, path, anchor=None, lines=None):
        return f"https://github.com/org/kb/blob/{sha}/{path}" + (f"#{anchor}" if anchor else "")

    def check_access(self):
        return {"ok": True}


def test_sync_full_then_incremental_then_remove(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "state_dir", str(tmp_path))
    kb = tmp_path / "kb"
    kb.mkdir()
    monkeypatch.setattr(s, "kb_dir", str(kb))
    monkeypatch.setattr(pipeline, "get_embedder", lambda: FakeEmbedder())
    repo = FakeRepo()
    monkeypatch.setattr(sources, "provider_for", lambda src: repo)
    pid = "git-" + uuid.uuid4().hex[:6]
    from rag_service.project_paths import upload_dir

    local = upload_dir(s, pid)
    local.mkdir(parents=True)
    (local / "local.md").write_text("# Локальный документ\n\n## Раздел\n\nТекст локального документа.\n", encoding="utf-8")
    src = sources.add(pid, "github", "org/kb", include=["docs/**/*.md"])

    rep = sources.sync(src["id"], describe=False)
    assert rep["status"] == "ok", rep
    assert rep["mode"] == "full" and rep["added"] == 2
    gen1 = store.active_generation(pid)
    chunks = store.scroll_all(pid, gen1)
    a = [c for c in chunks if c.get("git_path") == "docs/a.md"]
    assert a and a[0]["commit"] == "c1" and a[0]["source_url"].startswith("https://github.com/org/kb/blob/c1/docs/a.md")
    assert not any("main.py" in (c.get("git_path") or "") for c in chunks)

    # no new commit → nothing to do
    assert sources.sync(src["id"], describe=False)["status"] == "up_to_date"

    # FR-GIT-04: only the changed file is re-indexed, the other keeps its vectors
    files = dict(repo.commits["c1"])
    files["docs/a.md"] = files["docs/a.md"].replace("руководитель отдела", "директор")
    repo.commit("c2", files)
    repo.fetched.clear()
    rep = sources.sync(src["id"], describe=False)
    assert rep["status"] == "ok" and rep["mode"] == "incremental" and rep["modified"] == 1, rep
    assert repo.fetched == ["docs/a.md"]
    # FR-ADM-05: the sync report says what changed (for «Документация обновлена» / «Что изменилось»)
    assert [d["doc_id"] for d in rep["changes"]["changed"]] == [sources.git_doc_id(src["id"], "docs/a.md")]
    assert not rep["changes"]["added"] and not rep["changes"]["removed"] and rep["notified"] is False
    gen2 = store.active_generation(pid)
    assert gen2 != gen1
    chunks = store.scroll_all(pid, gen2)
    a = [c for c in chunks if c.get("git_path") == "docs/a.md"]
    b = [c for c in chunks if c.get("git_path") == "docs/b.md"]
    assert a and a[0]["commit"] == "c2" and "директор" in " ".join(c["text"] for c in a)
    assert b and b[0]["commit"] == "c1"  # untouched file keeps its version

    # removal in the repo removes the document
    files = dict(repo.commits["c2"])
    files.pop("docs/b.md")
    repo.commit("c3", files)
    rep = sources.sync(src["id"], describe=False)
    assert rep["removed"] == 1 and len(rep["changes"]["removed"]) == 1
    assert not [c for c in store.scroll_all(pid, store.active_generation(pid)) if c.get("git_path") == "docs/b.md"]

    # FR-GIT-07: a failing indexing keeps the previous generation
    gen3 = store.active_generation(pid)
    files = dict(files)
    files["docs/c.md"] = "# Новый\n\nтекст\n"
    repo.commit("c4", files)
    monkeypatch.setattr(pipeline, "get_embedder", lambda: (_ for _ in ()).throw(RuntimeError("embeddings down")))
    rep = sources.sync(src["id"], describe=False)
    assert rep["status"] == "failed" and store.active_generation(pid) == gen3
    assert sources.get(src["id"])["indexed_sha"] == "c3"

    monkeypatch.setattr(pipeline, "get_embedder", lambda: FakeEmbedder())
    out = sources.remove(src["id"])
    assert out["status"] == "ok" and out["removed_docs"] == 1
    left = store.scroll_all(pid, store.active_generation(pid))
    assert left and not [c for c in store.scroll_all(pid, store.active_generation(pid)) if c.get("git_path")]


def test_dim_change_does_not_wipe_index(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "qdrant_collection", "dimguard_" + uuid.uuid4().hex[:6])
    from qdrant_client import models as qm

    store.ensure_collection(8)
    store.upsert([qm.PointStruct(id=1, vector={"dense": [0.1] * 8}, payload={"project_id": "p"})])
    with pytest.raises(RuntimeError):
        store.ensure_collection(16)
    monkeypatch.setattr(s, "allow_collection_recreate", True)
    store.ensure_collection(16)
