"""Server-to-server adapter control. Credentials/hosts never come from panel input."""

import httpx

from . import confluence_source
from .config import get_settings


class ControlUnavailable(RuntimeError):
    pass


class ControlRejected(ControlUnavailable):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__("Confluence source link or configured scope was rejected")


def _request(method: str, path: str, *, params=None, body=None) -> dict:
    settings = get_settings()
    if not settings.confluence_control_url or not settings.confluence_control_token:
        raise ControlUnavailable("Confluence import service is not configured")
    try:
        with httpx.Client(base_url=settings.confluence_control_url,
                          headers={"Authorization": f"Bearer {settings.confluence_control_token}"},
                          timeout=settings.confluence_import_timeout_s) as client:
            response = client.request(method, path, params=params, json=body)
            if method == "POST" and response.status_code in {403, 404, 409, 422}:
                raise ControlRejected(response.status_code)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise ControlUnavailable("Confluence import service rejected or did not complete the request") from None
    if not isinstance(payload, dict):
        raise ControlUnavailable("Invalid Confluence import response")
    return payload


def list_sources(project_id: str) -> dict:
    result = _request("GET", "/sources", params={"project_id": project_id})
    sources = result.get("sources")
    if not isinstance(sources, list) or any(not isinstance(s, dict) or s.get("project_id") != project_id for s in sources):
        raise ControlUnavailable("Invalid Confluence source scope")
    result["sources"] += [s for s in confluence_source.allowed_sources().values()
                          if s.get("managed") and s.get("project_id") == project_id]
    return result


def register_source(project_id: str, template_source_id: str, page_url: str, include_children: bool) -> dict:
    result = _request("POST", "/sources/resolve", body={
        "project_id": project_id, "template_source_id": template_source_id,
        "page_url": page_url, "include_children": include_children,
    })
    try:
        return confluence_source.register_managed_source(project_id, result)
    except confluence_source.BatchError:
        raise ControlUnavailable("Confluence registration could not be verified") from None


def import_source(project_id: str, source_id: str, page_url: str) -> dict:
    source = confluence_source.allowed_sources().get(source_id)
    body = {"project_id": project_id, "page_url": page_url}
    if source and source.get("managed"):
        body["registered_source"] = source
    result = _request("POST", f"/sources/{source_id}/sync",
                      body=body)
    if result.get("source_id") != source_id or result.get("status") != "staged" or result.get("published") is not False:
        raise ControlUnavailable("Confluence did not confirm a staged import")
    return {**result, "status": "ok", "import_status": "staged"}
