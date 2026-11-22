"""Unauthenticated entry points that carry their own proof: signed document links and the Jira webhook."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import ApiError, not_found, unauthorized
from ..core.runtime import Core
from ..core.security import PUBLIC_ID_RE
from ..db.models import JiraSettings, Project
from ..services import escalations
from ..services.jira import parse_webhook, verify_signature
from ..services.rag import RagUnavailable
from .deps import get_core, get_db

log = logging.getLogger(__name__)
router = APIRouter(tags=["public"])
JIRA_BODY_MAX = 1024 * 1024
DOC_PATH_ALLOWED = ("view", "file")


@router.get("/v1/public/rag/documents/{doc_id}/{rest:path}")
async def document_link(doc_id: str, rest: str, request: Request, core: Core = Depends(get_core)) -> Response:
    """Source links in answers: `…/documents/{id}/view?project_id=&sig=` and its images. The RAG verifies `sig`
    (HMAC of project + document); this proxy only forwards the three read-only paths, never the service token."""
    head = rest.split("/", 1)[0]
    if head not in DOC_PATH_ALLOWED or ".." in rest or not request.query_params.get("sig"):
        raise not_found()
    params = {k: v for k, v in request.query_params.items() if k in ("project_id", "sig")}
    try:
        r = await core.rag.public_document(f"/documents/{doc_id}/{rest}", params)
    except RagUnavailable as e:
        raise ApiError(503, "llm_unavailable", "Сервис документов временно недоступен", retryable=True) from e
    if r.status_code != 200:
        raise not_found("document_not_found", "Документ не найден или ссылка недействительна")
    headers = {"Cache-Control": "private, max-age=300", "X-Robots-Tag": "noindex",
               "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"}
    if r.headers.get("content-disposition"):
        headers["Content-Disposition"] = r.headers["content-disposition"]
    return Response(r.content, media_type=r.headers.get("content-type"), headers=headers)


@router.post("/jira/webhook/{project_id}", status_code=204)
async def jira_webhook(project_id: str, request: Request, core: Core = Depends(get_core),
                       db: AsyncSession = Depends(get_db)) -> Response:
    """Jira → platform. Signed with the project's webhook secret: `X-Hub-Signature: sha256=<hex>`."""
    body = await request.body()
    if len(body) > JIRA_BODY_MAX or not PUBLIC_ID_RE.match(project_id):
        raise not_found()
    project = await db.scalar(select(Project).where(Project.public_id == project_id))
    js = await db.get(JiraSettings, project.id) if project else None
    secret = core.box.decrypt(js.webhook_secret_enc) if js else None
    if not verify_signature(body, request.headers.get("x-hub-signature"), secret):
        raise unauthorized("Неверная подпись вебхука")
    try:
        payload = json.loads(body)
    except ValueError:
        return Response(status_code=204)
    ev = parse_webhook(payload) if isinstance(payload, dict) else None
    if ev is not None:
        await escalations.on_jira_event(db, project, ev)
    return Response(status_code=204)
