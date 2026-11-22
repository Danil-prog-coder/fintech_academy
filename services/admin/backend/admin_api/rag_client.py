"""Client of the hidden RAG service. Only this module knows its URLs; everything goes with the service token.

Errors: network failures and 5xx → `RagUnavailable` (retryable for the caller); 4xx → `RagError` with the status.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

log = logging.getLogger(__name__)


class RagUnavailable(Exception):
    pass


class RagError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


def _detail(r: httpx.Response) -> str:
    try:
        body = r.json()
        return str(body.get("detail") or body.get("message") or body)[:300]
    except ValueError:
        return r.text[:300]


class RagClient:
    def __init__(self, base_url: str, token: str, timeout_s: float = 120.0, transport: httpx.AsyncBaseTransport | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers, transport=transport,
                                       timeout=httpx.Timeout(timeout_s, connect=5.0))
        # Without the service token: a signed document link must stand on its signature alone, otherwise
        # the proxy would open any document of any project to anyone who guesses a doc_id.
        self._public = httpx.AsyncClient(base_url=base_url.rstrip("/"), transport=transport,
                                         timeout=httpx.Timeout(30.0, connect=5.0))

    async def close(self) -> None:
        await self._http.aclose()
        await self._public.aclose()

    async def _request(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            r = await self._http.request(method, path, **kw)
        except httpx.HTTPError as e:
            log.warning("rag %s %s failed: %s", method, path, type(e).__name__)
            raise RagUnavailable(type(e).__name__) from e
        if r.status_code >= 500:
            raise RagUnavailable(f"{r.status_code}: {_detail(r)}")
        if r.status_code >= 400:
            raise RagError(r.status_code, _detail(r))
        return r

    async def _json(self, method: str, path: str, **kw) -> Any:
        return (await self._request(method, path, **kw)).json()

    # ---------------------------------------------------------------- dialog
    async def ask_stream(self, payload: dict) -> AsyncIterator[dict]:
        """SSE events of one turn: status / delta / reset / final."""
        try:
            async with self._http.stream("POST", "/ask", json=payload) as r:
                if r.status_code >= 400:
                    await r.aread()
                    if r.status_code >= 500:
                        raise RagUnavailable(f"{r.status_code}")
                    raise RagError(r.status_code, _detail(r))
                event, data = None, []
                async for line in r.aiter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        try:
                            ev = json.loads("\n".join(data))
                        except ValueError:
                            ev = None
                        if isinstance(ev, dict):
                            ev.setdefault("type", event)
                            yield ev
                        event, data = None, []
        except httpx.HTTPError as e:
            raise RagUnavailable(type(e).__name__) from e

    async def ask_sync(self, payload: dict) -> dict:
        return await self._json("POST", "/ask/sync", json=payload)

    async def reset_session(self, session_id: str, project_id: str) -> None:
        await self._request("POST", f"/sessions/{session_id}/reset", params={"project_id": project_id})

    async def feedback(self, request_id: str, rating: str, session_id: str | None, comment: str | None) -> dict:
        return await self._json("POST", "/feedback", json={"request_id": request_id, "rating": rating,
                                                           "session_id": session_id, "comment": comment})

    async def knowledge(self, project_id: str, question: str, answer: str, author: str | None, section: str | None) -> dict:
        return await self._json("POST", "/knowledge", json={"project_id": project_id, "question": question, "answer": answer,
                                                            "author": author, "section": section})

    async def faq_popular(self, project_id: str, limit: int = 5) -> dict:
        return await self._json("GET", "/faq/popular", params={"project_id": project_id, "limit": limit})

    async def image(self, project_id: str, image_id: str, crop: bool = False) -> httpx.Response:
        return await self._request("GET", f"/images/{image_id}", params={"project_id": project_id, "crop": str(crop).lower()})

    async def public_document(self, path: str, params: dict) -> httpx.Response:
        """Signed document links (`/documents/{id}/view?sig=`): the RAG service checks the signature itself."""
        try:
            r = await self._public.get(path, params=params)
        except httpx.HTTPError as e:
            raise RagUnavailable(type(e).__name__) from e
        return r

    # ---------------------------------------------------------------- knowledge base management
    async def documents(self, project_id: str) -> dict:
        return await self._json("GET", "/documents", params={"project_id": project_id})

    async def staged(self, project_id: str) -> dict:
        return await self._json("GET", "/documents/staged", params={"project_id": project_id})

    async def upload(self, project_id: str, section: str, mode: str, files: list[tuple[str, bytes, str]]) -> dict:
        data = {"project_id": project_id, "section": section, "mode": mode, "index": "true"}
        return await self._json("POST", "/documents", data=data,
                                files=[("files", (name, content, ctype)) for name, content, ctype in files])

    async def delete_document(self, project_id: str, doc_id: str) -> dict:
        return await self._json("DELETE", f"/documents/{doc_id}", params={"project_id": project_id})

    async def reindex(self, project_id: str) -> dict:
        return await self._json("POST", "/reindex", json={"project_id": project_id})

    async def jobs(self, project_id: str, limit: int = 20) -> dict:
        return await self._json("GET", "/jobs", params={"project_id": project_id, "limit": limit})

    async def rollback(self, project_id: str) -> dict:
        return await self._json("POST", "/rollback", params={"project_id": project_id})

    # ---------------------------------------------------------------- analytics and FAQ cache
    async def analytics_summary(self, project_id: str, days: int) -> dict:
        return await self._json("GET", "/analytics/summary", params={"project_id": project_id, "days": days})

    async def analytics_gaps(self, project_id: str, days: int) -> dict:
        return await self._json("GET", "/analytics/gaps", params={"project_id": project_id, "days": days})

    async def faq_entries(self, project_id: str) -> list:
        return await self._json("GET", "/faq/entries", params={"project_id": project_id})

    async def faq_recompute(self, project_id: str) -> dict:
        return await self._json("POST", "/faq/recompute", json={"project_id": project_id})

    async def faq_delete(self, project_id: str, entry_id: str) -> dict:
        return await self._json("DELETE", f"/faq/entries/{entry_id}", params={"project_id": project_id})

    async def health(self) -> dict:
        return await self._json("GET", "/health")
