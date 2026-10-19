from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.errors import AppError
from app.core.security import encrypt_secret
from app.db.models import Job, Repository, User
from app.db.session import get_session
from app.schemas.common import ERROR_RESPONSES
from app.schemas.repo import RepoConnectRequest, RepoStatus, RepoStatusResponse
from app.services.github import GitHubClient, get_github, parse_repo_url

router = APIRouter(tags=["repo"], responses=ERROR_RESPONSES)


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
        connected_at=repo.created_at,
    )


async def get_user_repo(session: AsyncSession, user_id: int) -> Repository | None:
    return await session.scalar(select(Repository).where(Repository.user_id == user_id))


@router.post("/repo/connect", response_model=RepoStatusResponse, status_code=201)
async def connect_repo(
    body: RepoConnectRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    github: GitHubClient = Depends(get_github),
):
    owner, name = parse_repo_url(body.url)
    existing = await get_user_repo(session, user.id)
    if existing is not None and not body.replace:
        raise AppError(
            "repo_exists",
            "Репозиторий уже подключён. Повторите запрос с replace=true, чтобы заменить его.",
            409,
        )

    await github.check_access(owner, name, body.github_token)

    if existing is not None:
        await session.execute(delete(Job).where(Job.repo_id == existing.id))
        await session.delete(existing)
        await session.flush()

    repo = Repository(
        user_id=user.id,
        url=f"https://github.com/{owner}/{name}",
        owner=owner,
        name=name,
        github_token_encrypted=encrypt_secret(body.github_token) if body.github_token else None,
        status=RepoStatus.indexing,
    )
    session.add(repo)
    await session.flush()
    session.add(Job(repo_id=repo.id, type="index_full", payload={}))
    await session.commit()
    return to_status_response(repo)


@router.get("/repo/status", response_model=RepoStatusResponse)
async def repo_status(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    return to_status_response(await get_user_repo(session, user.id))


@router.delete("/repo", status_code=204)
async def disconnect_repo(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    repo = await get_user_repo(session, user.id)
    if repo is None:
        raise AppError("repo_not_connected", "Репозиторий не подключён.", 404)
    await session.execute(delete(Job).where(Job.repo_id == repo.id))
    await session.delete(repo)
    await session.commit()
