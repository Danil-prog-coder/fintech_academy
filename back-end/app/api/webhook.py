import json

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Job, Repository
from app.db.session import get_session
from app.schemas.common import ERROR_RESPONSES
from app.services.github import verify_signature

router = APIRouter(tags=["github"], responses=ERROR_RESPONSES)


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
    except (ValueError, KeyError, TypeError):
        raise AppError("invalid_payload", "Некорректное тело вебхука.", 400)

    repo = await session.scalar(
        select(Repository).where(Repository.owner == owner, Repository.name == name)
    )
    if repo is None:
        return WebhookResponse(accepted=False, detail="репозиторий не подключён")

    # Идемпотентность: повторная доставка того же коммита не создаёт второй задачи.
    jobs = await session.scalars(
        select(Job).where(Job.repo_id == repo.id, Job.type == "index_update")
    )
    if any(j.payload.get("after") == after for j in jobs):
        return WebhookResponse(accepted=True, detail="уже в очереди")

    session.add(Job(repo_id=repo.id, type="index_update", payload={"after": after}))
    if repo.status == "ready":
        repo.status = "updating"
    await session.commit()
    return WebhookResponse(accepted=True)
