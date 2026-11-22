"""FR-ADM-05: what changed between generations + the optional docs.updated push."""

import rag_service.ingest.notify as notify
from rag_service.core.config import get_settings

B = {"documents": [{"doc_id": "a", "title": "A", "content_hash": "1", "outline": ["1 Вход", "2 Меню"]},
                   {"doc_id": "gone", "title": "Старый", "content_hash": "x"}]}
A = {"documents": [{"doc_id": "a", "title": "A", "content_hash": "2", "outline": ["1 Вход", "3 Отчёты"]},
                   {"doc_id": "new", "title": "Новый", "content_hash": "y"}]}


def test_manifest_diff_and_summary():
    d = notify.manifest_diff(B, A)
    assert [x["doc_id"] for x in d["added"]] == ["new"] and [x["doc_id"] for x in d["removed"]] == ["gone"]
    assert d["changed"][0]["sections_added"] == ["3 Отчёты"] and d["changed"][0]["sections_removed"] == ["2 Меню"]
    t = notify.summary_text(d)
    assert "Новый документ: Новый" in t and "новые разделы: 3 Отчёты" in t and "Удалён документ: Старый" in t
    assert notify.is_empty(notify.manifest_diff(A, A))


def test_push_only_when_configured_and_changed(monkeypatch):
    sent = []

    class R:
        def raise_for_status(self):
            pass

    import httpx

    monkeypatch.setattr(httpx, "post", lambda url, json, headers, timeout: sent.append((url, json, headers)) or R())
    s = get_settings()
    d = notify.manifest_diff(B, A)
    assert notify.push_docs_updated("p", "g2", "git:org/repo", d, background=False) is False  # URL not set
    monkeypatch.setattr(s, "docs_webhook_url", "http://bot/internal/events")
    monkeypatch.setattr(s, "docs_webhook_token", "t")
    assert notify.push_docs_updated("p", "g2", "git:org/repo", notify.manifest_diff(A, A), background=False) is False
    assert notify.push_docs_updated("p", "g2", "git:org/repo", d, background=False) is True
    url, body, headers = sent[0]
    ev = body["events"][0]
    assert ev["type"] == "docs.updated" and ev["data"]["changes"] == d and headers == {"X-Service-Token": "t"}
