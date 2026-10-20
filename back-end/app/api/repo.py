from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import Chunk, IndexVersion, Job, Repository, User
from app.db.session import get_session
from app.schemas.common import ERROR_RESPONSES
from app.schemas.repo import RepoConnectRequest, RepoStatus, RepoStatusResponse
from app.services.github import GitHubClient, get_github, parse_repo_url

router = APIRouter(tags=["repo"], responses=ERROR_RESPONSES)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def webhook_target() -> str | None:
    """Публичный адрес приёма вебхука или None, если GitHub до него не достучится."""
    base = get_settings().public_base_url.rstrip("/")
    host = urlparse(base).hostname or ""
    if host in _LOCAL_HOSTS or host.endswith(".local"):
        return None
    return f"{base}/github/webhook"


def _webhook_hint(repo: Repository) -> str | None:
    if repo.webhook_id is not None:
        return None
    target = webhook_target() or "<PUBLIC_BASE_URL>/github/webhook"
    return (
        "Автоматическое обновление индекса не настроено. В настройках репозитория на GitHub "
        f"добавьте вебхук: адрес {target}, формат application/json, событие push, "
        "секрет из GITHUB_WEBHOOK_SECRET."
    )


def to_status_response(repo: Repository | None) -> RepoStatusResponse:
    if repo is None:
        return RepoStatusResponse(status=RepoStatus.not_connected)
    return RepoStatusResponse(
        status=RepoStatus(repo.status),
        url=repo.url,
        owner=repo.owner,
        name=repo.name,
        last_commit=repo.last_commit,
        webhook_registered=repo.webhook_id is not None,
        webhook_hint=_webhook_hint(repo),
        last_error=repo.last_error,
        indexed_files=repo.indexed_files,
        skipped_files=repo.skipped_files,
        connected_at=repo.created_at,
    )


async def get_user_repo(session: AsyncSession, user_id: int) -> Repository | None:
    return await session.scalar(select(Repository).where(Repository.user_id == user_id))


async def purge_repo(session: AsyncSession, repo: Repository) -> None:
    """Удаляет репозиторий вместе с индексом и задачами."""
    await session.execute(delete(Job).where(Job.repo_id == repo.id))
    await session.execute(delete(Chunk).where(Chunk.repo_id == repo.id))
    await session.execute(delete(IndexVersion).where(IndexVersion.repo_id == repo.id))
    await session.delete(repo)
    await session.flush()


async def _drop_webhook(github: GitHubClient, repo: Repository) -> None:
    if repo.webhook_id is not None and repo.github_token_encrypted:
        await github.delete_webhook(
            repo.owner, repo.name, decrypt_secret(repo.github_token_encrypted), repo.webhook_id
        )


@router.post("/repo/connect", response_model=RepoStatusResponse, status_code=201)
async def connect_repo(
    body: RepoConnectRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    github: GitHubClient = Depends(get_github),
):
    settings = get_settings()
    owner, name = parse_repo_url(body.url)
    existing = await get_user_repo(session, user.id)
    if existing is not None and not body.replace:
        raise AppError(
            "repo_exists",
            "Репозиторий уже подключён. Повторите запрос с replace=true, чтобы заменить его.",
            409,
        )

    info = await github.check_access(owner, name, body.github_token)

    # Вебхук создаём сами, если есть токен и публичный адрес. Иначе — подсказка в статусе.
    webhook_id = None
    target = webhook_target()
    if body.github_token and target and settings.github_webhook_secret:
        webhook_id = await github.create_webhook(
            owner, name, body.github_token, target, settings.github_webhook_secret
        )

    if existing is not None:
        await _drop_webhook(github, existing)
        await purge_repo(session, existing)

    repo = Repository(
        user_id=user.id,
        url=f"https://github.com/{owner}/{name}",
        owner=owner,
        name=name,
        github_token_encrypted=encrypt_secret(body.github_token) if body.github_token else None,
        status=RepoStatus.indexing,
        default_branch=info.default_branch,
        webhook_id=webhook_id,
    )
    session.add(repo)
    try:
        await session.flush()
        session.add(Job(repo_id=repo.id, type="index_full", payload={}))
        await session.commit()
    except IntegrityError:  # два одновременных подключения одного пользователя
        await session.rollback()
        raise AppError("repo_exists", "Репозиторий уже подключается. Обновите страницу.", 409)
    return to_status_response(repo)


@router.get("/repo/status", response_model=RepoStatusResponse)
async def repo_status(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    return to_status_response(await get_user_repo(session, user.id))


@router.delete("/repo", status_code=204)
async def disconnect_repo(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    github: GitHubClient = Depends(get_github),
):
    repo = await get_user_repo(session, user.id)
    if repo is None:
        raise AppError("repo_not_connected", "Репозиторий не подключён.", 404)
    await _drop_webhook(github, repo)
    await purge_repo(session, repo)
    await session.commit()
