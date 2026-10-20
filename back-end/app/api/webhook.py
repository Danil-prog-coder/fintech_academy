import json

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Job, Repository
from app.db.session import get_session
from app.schemas.common import ERROR_RESPONSES
from app.services.github import verify_signature

router = APIRouter(tags=["github"], responses=ERROR_RESPONSES)

_ZERO_SHA = "0" * 40


class WebhookResponse(BaseModel):
    accepted: bool
    detail: str | None = None


@router.post("/github/webhook", response_model=WebhookResponse)
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
):
    secret = get_settings().github_webhook_secret
    if not secret:
        raise AppError("webhook_not_configured", "Вебхук не настроен на сервере.", 503)

    body = await request.body()
    if not verify_signature(secret, body, x_hub_signature_256):
        raise AppError("invalid_signature", "Неверная подпись вебхука.", 401)

    if x_github_event == "ping":
        return WebhookResponse(accepted=True, detail="pong")
    if x_github_event != "push":
        return WebhookResponse(accepted=False, detail="событие игнорируется")

    try:
        payload = json.loads(body)
        owner, name = payload["repository"]["full_name"].split("/", 1)
        after = payload["after"]
        ref = payload.get("ref")
    except (ValueError, KeyError, TypeError, AttributeError):
        raise AppError("invalid_payload", "Некорректное тело вебхука.", 400)
    if payload.get("deleted") or after == _ZERO_SHA:
        return WebhookResponse(accepted=False, detail="ветка удалена")

    # GitHub не различает регистр в именах; один репозиторий могут подключить несколько людей.
    repos = (
        await session.scalars(
            select(Repository).where(
                func.lower(Repository.owner) == owner.lower(),
                func.lower(Repository.name) == name.lower(),
            )
        )
    ).all()
    if not repos:
        return WebhookResponse(accepted=False, detail="репозиторий не подключён")

    queued = fresh = 0
    for repo in repos:
        # Индексируем только основную ветку.
        if ref and repo.default_branch and ref != f"refs/heads/{repo.default_branch}":
            continue
        jobs = await session.scalars(
            select(Job).where(Job.repo_id == repo.id, Job.type == "index_update")
        )
        # Идемпотентность: повторная доставка того же коммита не создаёт второй задачи.
        if any(j.payload.get("after") == after for j in jobs):
            queued += 1
            continue
        fresh += 1
        session.add(Job(repo_id=repo.id, type="index_update", payload={"after": after}))
        if repo.status == "ready":
            repo.status = "updating"
        queued += 1
    await session.commit()
    if queued == 0:
        return WebhookResponse(accepted=False, detail="ветка не основная")
    return WebhookResponse(accepted=True, detail=None if fresh else "уже в очереди")
