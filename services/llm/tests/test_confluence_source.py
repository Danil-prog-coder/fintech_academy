"""Confluence batches (Docs/contract/confluence-batches.md): idempotency, ordering, scoped deletes, verbatim content."""

import base64
import hashlib
import json
import os
import subprocess
import sys

import pytest

from rag_service.core.config import get_settings
from rag_service.sources import confluence as cs

PAGE_HTML = (
    "<h2>Фильтры</h2><p>Пример: <code>status in A|B|C</code> и <code>sum != 0</code>.</p>"
    "<table><tbody><tr><th>Поле</th><th>Условие</th></tr><tr><td>Статус</td><td>&gt; 1</td></tr></tbody></table>"
    '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">sql</ac:parameter>'
    "<ac:plain-text-body><![CDATA[select * from t where a !> 1]]></ac:plain-text-body></ac:structured-macro>"
    "<ul><li>первый</li><li>второй</li></ul>"
)


@pytest.fixture
def source(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "state_dir", str(tmp_path))
    monkeypatch.setattr(s, "confluence_sources", json.dumps({"confluence-barser": {"project_id": "default"}}))
    started = []

    def start(project_id):
        started.append(project_id)
        return f"job-{len(started)}"

    return start, started


def doc(page_id="393218", *, version=1, deleted=False, html=PAGE_HTML, attachments=()):
    return {
        "document_id": f"confluence-barser:page:{page_id}", "page_id": page_id, "version": version,
        "title": "Регламент БАРС-Офиса", "space_id": "65903", "project_id": "evil", "section": "general",
        "source_url": f"https://barsbarser1.atlassian.net/wiki/spaces/BARSER/pages/{page_id}",
        "content_html": "" if deleted else html, "content_text": "", "content_hash": "h", "deleted": deleted,
        "delete_reason": "deleted" if deleted else None, "metadata": {}, "attachments": list(attachments),
    }


def batch(seq, *docs):
    return {"batch_id": f"confluence-barser:{seq:08d}:x", "source_id": "confluence-barser", "source_sequence": seq,
            "source_binding": "b", "documents": list(docs)}


def test_storage_html_keeps_tables_code_and_filters_verbatim():
    md = cs.storage_to_markdown(PAGE_HTML)
    assert "## Фильтры" in md and "status in A|B|C" in md and "sum != 0" in md
    assert "| Статус | > 1 |" in md
    assert "```\nselect * from t where a !> 1\n```" in md and "language" not in md
    assert "- первый" in md and "- второй" in md


def test_batch_is_indexed_with_page_link_and_trusted_project(source):
    start, started = source
    receipt = cs.receive_batch("confluence-barser", batch(1, doc()), start)
    assert receipt == {"batch_id": "confluence-barser:00000001:x", "accepted": True, "job_id": "job-1", "message": ""}
    assert started == ["default"], "project from the allowlist, not from the payload"
    (path, meta), = cs.local_files("default")
    assert meta["url"].endswith("/pages/393218") and meta["source_type"] == "confluence"
    assert path.read_text(encoding="utf-8").startswith("# Регламент БАРС-Офиса")
    assert cs.local_files("other") == []


def test_repeated_batch_returns_original_receipt_and_stale_is_not_applied(source):
    start, started = source
    first = cs.receive_batch("confluence-barser", batch(2, doc()), start)
    assert cs.receive_batch("confluence-barser", batch(2, doc()), start) == first
    stale = cs.receive_batch("confluence-barser", batch(1, doc(deleted=True)), start)
    assert stale["accepted"] is True and stale["job_id"] is None
    assert len(cs.local_files("default")) == 1 and started == ["default"]


def test_delete_revokes_only_this_document(source):
    start, _ = source
    cs.receive_batch("confluence-barser", batch(1, doc("1"), doc("2")), start)
    cs.receive_batch("confluence-barser", batch(2, doc("1", deleted=True)), start)
    (_, meta), = cs.local_files("default")
    assert meta["url"].endswith("/pages/2")


def test_pdf_attachment_is_stored_and_checked(source):
    start, _ = source
    data = b"%PDF-1.4 test"
    att = {"attachment_id": "att1", "filename": "scheme.pdf", "has_data": True,
           "content_base64": base64.b64encode(data).decode(), "sha256": hashlib.sha256(data).hexdigest()}
    cs.receive_batch("confluence-barser", batch(1, doc(attachments=[att])), start)
    files = {p.name: m for p, m in cs.local_files("default")}
    assert "att1-scheme.pdf" in files and files["att1-scheme.pdf"]["path"].endswith("/scheme.pdf")
    bad = dict(att, sha256="0" * 64)
    with pytest.raises(cs.BatchError):
        cs.receive_batch("confluence-barser", batch(2, doc(attachments=[bad])), start)


def test_unknown_source_and_bad_payload_are_rejected(source):
    start, _ = source
    with pytest.raises(cs.BatchError) as unknown:
        cs.receive_batch("other", dict(batch(1, doc()), source_id="other"), start)
    assert unknown.value.unknown_source
    with pytest.raises(cs.BatchError):
        cs.receive_batch("confluence-barser", dict(batch(1, doc()), source_binding=""), start)
    with pytest.raises(cs.BatchError):
        cs.receive_batch("confluence-barser", dict(batch(1, doc()), source_id="x"), start)


def test_job_status_in_contract_shape():
    assert cs.contract_job({"job_id": "j", "status": "queued"})["status"] == "pending"
    assert cs.contract_job({"job_id": "j", "status": "done"}) == {"job_id": "j", "status": "done", "message": ""}
    failed = cs.contract_job({"job_id": "j", "status": "failed", "error": "embeddings down"})
    assert failed["status"] == "error" and "embeddings" in failed["message"]


def test_invalid_update_preserves_previous_files_and_sequence(source):
    start, _ = source
    cs.receive_batch("confluence-barser", batch(1, doc()), start)
    original = cs.local_files("default")[0][0]
    content = original.read_bytes()
    bad = {"filename": "bad.pdf", "has_data": True, "content_base64": "!!!!"}
    with pytest.raises(cs.BatchError):
        cs.receive_batch("confluence-barser", batch(2, doc(attachments=[bad])), start)
    assert original.read_bytes() == content
    assert cs._load()["confluence-barser"]["applied_sequence"] == 1


def test_index_worker_sees_saved_batch_and_failed_start_can_retry(source):
    start, _ = source

    def fail(project_id):
        assert len(cs.local_files(project_id)) == 1
        raise RuntimeError("worker unavailable")

    with pytest.raises(RuntimeError):
        cs.receive_batch("confluence-barser", batch(1, doc()), fail)
    assert cs.local_files("default") == []
    cs.receive_batch("confluence-barser", batch(1, doc()), start)
    assert len(cs.local_files("default")) == 1


def test_reusing_batch_id_with_other_bytes_is_rejected(source):
    start, _ = source
    cs.receive_batch("confluence-barser", batch(1, doc()), start)
    with pytest.raises(cs.BatchError, match="different content"):
        cs.receive_batch("confluence-barser", batch(1, doc(deleted=True)), start)


def test_received_page_uses_structured_parser_with_local_images(source, tmp_path):
    from rag_service.ingest.pipeline import parse_with_meta

    start, _ = source
    image = b"test image bytes"
    attachment = {"attachment_id": "img1", "filename": "screen.png", "has_data": True,
                  "content_base64": base64.b64encode(image).decode(),
                  "sha256": hashlib.sha256(image).hexdigest()}
    html = ('<table><tr><td>status in A|B|C</td><td>!= 0</td></tr></table>'
            '<ac:image><ri:attachment ri:filename="screen.png"/></ac:image>')
    cs.receive_batch("confluence-barser", batch(1, doc(html=html, attachments=[attachment])), start)
    (path, meta), = cs.local_files("default")
    parsed = parse_with_meta(path, tmp_path / "images", meta)
    assert parsed.source_type == "confluence"
    assert parsed.doc_id == meta["doc_id"]
    assert next(b for b in parsed.blocks if b.kind == "table").rows == [["status in A|B|C", "!= 0"]]
    block = next(b for b in parsed.blocks if b.kind == "image")
    from pathlib import Path
    assert Path(block.image_path).read_bytes() == image
    assert meta["url"].endswith("/pages/393218")


def test_legacy_manifest_without_storage_uses_markdown(source, tmp_path):
    from rag_service.ingest.pipeline import parse_with_meta

    start, _ = source
    cs.receive_batch("confluence-barser", batch(1, doc()), start)
    path, meta = cs.local_files("default")[0]
    meta.pop("confluence_storage")
    assert parse_with_meta(path, tmp_path, meta).source_type == "confluence"


def test_staging_compares_published_fingerprints_after_reloading(source):
    start, _ = source
    cs.receive_batch("confluence-barser", batch(1, doc()), None)
    staged = cs.staging_status("default", {})
    assert staged["count"] == 1 and staged["documents"][0]["change"] == "added"
    _, meta = cs.local_files("default")[0]
    manifest = {"generation": "active-1", "documents": [{
        "doc_id": meta["doc_id"], "source_type": "confluence",
        "confluence_fingerprint": meta["confluence_fingerprint"],
        "git": {"source_id": meta["source_id"], "url": meta["url"]},
    }]}
    assert not cs.staging_status("default", manifest)["has_changes"]
    cs.receive_batch("confluence-barser", batch(2, doc(version=2)), None)
    update = cs.staging_status("default", manifest)
    assert update["active_generation"] == "active-1"
    assert update["documents"][0]["change"] == "updated"
    assert cs.staging_status("other", {})["count"] == 0
    cs.receive_batch("confluence-barser", batch(3, doc(deleted=True)), None)
    removed = cs.staging_status("default", manifest)
    assert removed["documents"][0]["change"] == "removed"
    assert removed["bytes"] == 0


def test_image_only_update_changes_page_fingerprint(source):
    start, _ = source
    def image(data):
        return {"filename": "screen.png", "attachment_id": "img1", "has_data": True,
                "content_base64": base64.b64encode(data).decode()}
    cs.receive_batch("confluence-barser", batch(1, doc(attachments=[image(b"old")])), None)
    old = cs.local_files("default")[0][1]["confluence_fingerprint"]
    cs.receive_batch("confluence-barser", batch(2, doc(attachments=[image(b"new")])), None)
    assert cs.local_files("default")[0][1]["confluence_fingerprint"] != old


def test_staging_receipt_and_manifest_are_written_once_atomically(source, monkeypatch):
    saves = []
    original = cs._save
    def save(state):
        saves.append(json.loads(json.dumps(state)))
        original(state)
    monkeypatch.setattr(cs, "_save", save)
    receipt = cs.receive_batch("confluence-barser", batch(1, doc()))
    assert len(saves) == 1
    st = saves[0]["confluence-barser"]
    assert st["receipts"][receipt["batch_id"]] == receipt
    assert st["documents"] and st["payload_hashes"][receipt["batch_id"]]


def test_source_binding_cannot_silently_change(source):
    cs.receive_batch("confluence-barser", batch(1, doc()))
    with pytest.raises(cs.BatchError, match="binding changed"):
        cs.receive_batch("confluence-barser", dict(batch(2, doc()), source_binding="other"))
    assert cs._load()["confluence-barser"]["applied_sequence"] == 1


def test_managed_page_registration_survives_reload_and_template_revocation(source, monkeypatch):
    item = {"source_id": "managed-" + "a" * 24, "project_id": "default", "space_id": "65903",
            "root_page_id": "2", "section": "general", "include_children": True,
            "source_binding": "b" * 32, "template_binding": "c" * 32,
            "template_source_id": "confluence-barser", "managed": True,
            "page_url": "https://example.test/wiki/pages/2"}
    saved = cs.register_managed_source("default", item)
    assert cs.register_managed_source("default", item) == saved
    assert cs.allowed_sources()[item["source_id"]]["root_page_id"] == "2"
    page = dict(doc("2"), document_id=f"{item['source_id']}:page:2")
    cs.receive_batch(item["source_id"], {"source_id": item["source_id"], "batch_id": "m1",
        "source_sequence": 1, "source_binding": "b" * 32, "documents": [page]})
    assert cs.local_files("default")[0][1]["source_id"] == item["source_id"]
    monkeypatch.setattr(get_settings(), "confluence_sources", json.dumps({
        "confluence-barser": {"project_id": "other"}}))
    assert item["source_id"] not in cs.allowed_sources()
    assert cs.local_files("default") == []


@pytest.mark.parametrize("change", [
    {"document_id": "other:page:393218"}, {"page_id": "../1"}, {"deleted": "false"},
    {"content_html": {}}, {"attachments": ["bad"]},
])
def test_malformed_document_is_rejected_before_mutation(source, change):
    with pytest.raises(cs.BatchError):
        cs.receive_batch("confluence-barser", batch(1, dict(doc(), **change)))
    assert cs.local_files("default") == []


def test_separate_receiver_processes_do_not_lose_each_others_sources(tmp_path):
    script = '''
import sys
from rag_service.sources.confluence import receive_batch
source = sys.argv[1]
for seq in range(1, 7):
    receive_batch(source, {"source_id": source, "batch_id": f"{source}:{seq}",
        "source_sequence": seq, "source_binding": "binding", "documents": [{
        "document_id": f"{source}:page:{seq}", "page_id": str(seq),
        "title": source, "content_html": "<p>version</p>"}]})
'''
    env = dict(os.environ, STATE_DIR=str(tmp_path), CONFLUENCE_SOURCES=json.dumps({
        "source-a": {"project_id": "default"}, "source-b": {"project_id": "default"}}))
    processes = [subprocess.Popen([sys.executable, "-c", script, source], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for source in ("source-a", "source-b")]
    try:
        for process in processes:
            _, error = process.communicate(timeout=30)
            assert process.returncode == 0, error.decode(errors="replace")
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    state = json.loads((tmp_path / "confluence" / "state.json").read_text(encoding="utf-8"))
    assert set(state) == {"source-a", "source-b"}
    assert all(len(s["documents"]) == 6 and s["applied_sequence"] == 6 for s in state.values())


@pytest.mark.parametrize("seq", [True, 0, -1, 1.5, "1"])
def test_invalid_sequence_is_rejected(source, seq):
    start, _ = source
    with pytest.raises(cs.BatchError):
        cs.receive_batch("confluence-barser", batch(seq) if type(seq) is int else
                         dict(batch(1), source_sequence=seq), start)
