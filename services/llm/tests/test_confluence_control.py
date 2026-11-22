import httpx
import pytest

from rag_service.core.config import get_settings
from rag_service.sources import confluence_control as control


@pytest.fixture
def remote(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "confluence_control_url", "http://adapter.test")
    monkeypatch.setattr(settings, "confluence_control_token", "private")
    calls = []
    original = httpx.Client
    def install(payload, status=200):
        def respond(request):
            calls.append(request)
            return httpx.Response(status, json=payload)
        monkeypatch.setattr(control.httpx, "Client", lambda **kwargs: original(
            **kwargs, transport=httpx.MockTransport(respond)))
    return install, calls


def test_lists_only_requested_project(remote):
    install, calls = remote
    install({"sources": [{"source_id": "team", "project_id": "default"}]})
    assert control.list_sources("default")["sources"][0]["source_id"] == "team"
    assert calls[0].headers["Authorization"] == "Bearer private"
    assert calls[0].url.params["project_id"] == "default"
    install({"sources": [{"source_id": "team", "project_id": "other"}]})
    with pytest.raises(control.ControlUnavailable):
        control.list_sources("default")


def test_import_requires_explicit_staged_result(remote):
    install, _ = remote
    install({"source_id": "team", "status": "staged", "published": False})
    assert control.import_source("default", "team", "")["import_status"] == "staged"
    install({"source_id": "team", "status": "done", "published": True})
    with pytest.raises(control.ControlUnavailable):
        control.import_source("default", "team", "")


def test_upstream_errors_do_not_expose_response_body(remote):
    install, _ = remote
    install({"detail": "signed-url-secret"}, 502)
    with pytest.raises(control.ControlUnavailable) as error:
        control.list_sources("default")
    assert "secret" not in str(error.value)
