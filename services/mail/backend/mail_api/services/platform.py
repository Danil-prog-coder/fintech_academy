"""Client of the platform's open API (/v1). The mail demo is an ordinary integration: what it does here, any
messenger or portal can do with the same calls. Our user's id (`users.id`) is the `external_id` on the platform."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from mail_api.core.errors import AppError

log = logging.getLogger(__name__)


def external_id(user_id: int) -> str:
    return f"mail-user-{user_id}"


def user_id_of(external: str) -> int | None:
    if external.startswith("mail-user-") and external[10:].isdigit():
        return int(external[10:])
    return None


class PlatformClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), headers={"X-Api-Key": api_key},
                                       timeout=httpx.Timeout(timeout, connect=5.0), transport=transport)
        self.configured = bool(api_key)

    async def close(self) -> None:
        await self._http.aclose()

    async def call(self, method: str, path: str, **kw) -> Any:
        if not self.configured:
            raise AppError("platform_not_configured", "Платформа не настроена: нет PLATFORM_API_KEY.", 503, True)
        try:
            r = await self._http.request(method, path, **kw)
        except httpx.HTTPError as e:
            log.warning("platform %s %s: %s", method, path.split("?")[0], type(e).__name__)
            raise AppError("platform_unavailable", "Платформа временно недоступна.", 503, True) from e
        if r.status_code == 204:
            return None
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400:
            # the platform's errors share our format: pass code and message through
            raise AppError(body.get("code", "platform_error"), body.get("message", "Ошибка платформы."),
                           r.status_code if r.status_code < 500 else 502, bool(body.get("retryable")))
        return body

    # projects and statuses
    async def create_project(self, name: str, owner: str, login: str, display_name: str | None) -> dict:
        return await self.call("POST", "/v1/projects", json={"name": name, "owner_external_id": owner,
                                                            "owner_login": login, "owner_display_name": display_name})

    async def join_project(self, ext: str, project_code: str, login: str | None, display_name: str | None) -> dict:
        return await self.call("POST", "/v1/projects/join", json={"external_id": ext, "project_code": project_code,
                                                                 "login": login, "display_name": display_name})

    async def projects_of(self, ext: str) -> list[dict]:
        return (await self.call("GET", "/v1/projects", params={"external_id": ext}))["projects"]

    async def members(self, project_id: str) -> list[dict]:
        return (await self.call("GET", f"/v1/projects/{project_id}/members"))["members"]

    async def sections(self, project_id: str) -> list[dict]:
        return (await self.call("GET", f"/v1/projects/{project_id}/sections"))["sections"]

    async def put_member(self, project_id: str, ext: str, body: dict) -> dict:
        return await self.call("PUT", f"/v1/projects/{project_id}/members/{ext}", json=body)

    async def delete_member(self, project_id: str, ext: str, acting: str) -> None:
        await self.call("DELETE", f"/v1/projects/{project_id}/members/{ext}", params={"acting_external_id": acting})

    async def password_reset(self, project_id: str, ext: str, acting: str) -> dict:
        return await self.call("POST", f"/v1/projects/{project_id}/members/{ext}/panel-password-reset",
                               json={"acting_external_id": acting})

    # questions
    async def ask(self, project_id: str, ext: str, message: str, channel: str = "mail", *,
                  images: list[dict] | None = None, attachments: list[dict] | None = None) -> dict:
        body = {"external_id": ext, "message": message, "channel": channel}
        if images:
            body["images"] = images
        if attachments:
            body["attachments"] = attachments
        return await self.call("POST", f"/v1/projects/{project_id}/ask", json=body)

    async def transcribe(self, project_id: str, ext: str, data_base64: str, mime: str) -> dict:
        return await self.call("POST", f"/v1/projects/{project_id}/transcribe",
                               json={"external_id": ext, "data_base64": data_base64, "mime": mime})

    async def reset_dialog(self, project_id: str, ext: str) -> None:
        await self.call("POST", f"/v1/projects/{project_id}/members/{ext}/reset-dialog")

    async def feedback(self, project_id: str, ext: str, request_id: str, value: int) -> dict:
        return await self.call("POST", f"/v1/projects/{project_id}/feedback",
                               json={"external_id": ext, "request_id": request_id, "value": value})

    async def popular(self, project_id: str) -> list:
        return (await self.call("GET", f"/v1/projects/{project_id}/faq/popular"))["questions"]

    async def image(self, project_id: str, image_id: str) -> httpx.Response:
        if not self.configured:
            raise AppError("platform_not_configured", "Платформа не настроена.", 503, True)
        try:
            r = await self._http.get(f"/v1/projects/{project_id}/images/{image_id}")
        except httpx.HTTPError as e:
            raise AppError("platform_unavailable", "Платформа временно недоступна.", 503, True) from e
        if r.status_code != 200:
            raise AppError("not_found", "Картинка не найдена.", 404)
        return r

    # support tickets
    async def escalate(self, project_id: str, ext: str, message: str | None, request_id: str | None) -> dict:
        return await self.call("POST", f"/v1/projects/{project_id}/escalations",
                               json={"external_id": ext, "message": message, "request_id": request_id})

    async def escalations(self, project_id: str, ext: str) -> list[dict]:
        return (await self.call("GET", f"/v1/projects/{project_id}/escalations", params={"external_id": ext}))["escalations"]

    async def escalation(self, project_id: str, ext: str, key: str) -> dict:
        return await self.call("GET", f"/v1/projects/{project_id}/escalations/{key}", params={"external_id": ext})

    async def escalation_message(self, project_id: str, ext: str, key: str, text: str) -> dict:
        return await self.call("POST", f"/v1/projects/{project_id}/escalations/{key}/messages",
                               json={"external_id": ext, "text": text})

    async def events(self, after: int, limit: int = 200) -> dict:
        return await self.call("GET", "/v1/events", params={"after": after, "limit": limit})
