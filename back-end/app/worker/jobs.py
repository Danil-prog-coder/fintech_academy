"""Очередь задач на таблице jobs (SELECT ... FOR UPDATE SKIP LOCKED)."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.runtime import Services
from app.db.models import Job, Repository
from app.llm.base import LLMAuthError, LLMError, LLMNotConfiguredError
from app.services.github import GitHubAuthError, GitHubUnavailableError
from app.services.indexer import index_repository

log = logging.getLogger(__name__)

Sessions = async_sessionmaker[AsyncSession]


def _now() -> datetime:
    return datetime.now(UTC)


async def recover_stale(sessions: Sessions) -> int:
    """Задачи, брошенные упавшим worker, возвращаем в очередь."""
    limit = _now() - timedelta(minutes=get_settings().worker_stale_minutes)
    async with sessions() as s, s.begin():
        result = await s.execute(
            update(Job).where(Job.status == "running", Job.started_at < limit).values(status="pending")
        )
    return result.rowcount or 0


async def claim(sessions: Sessions) -> Job | None:
    async with sessions() as s, s.begin():
        job = await s.scalar(
            select(Job)
            .where(Job.status == "pending", Job.run_after <= _now())
            .order_by(Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.status, job.started_at, job.attempts = "running", _now(), job.attempts + 1
        await s.flush()
        s.expunge(job)
        return job


async def _finish(
    sessions: Sessions, job_id: int, status: str, error: str | None = None, retry_in: int = 0
) -> None:
    async with sessions() as s, s.begin():
        values: dict = {"status": status, "error": error}
        if status == "pending":
            values["run_after"] = _now() + timedelta(seconds=retry_in)
        await s.execute(update(Job).where(Job.id == job_id).values(**values))


async def _set_repo(sessions: Sessions, repo_id: int, **values) -> None:
    async with sessions() as s, s.begin():
        await s.execute(update(Repository).where(Repository.id == repo_id).values(**values))


async def _has_index(sessions: Sessions, repo_id: int) -> bool:
    async with sessions() as s:
        repo = await s.get(Repository, repo_id)
        return bool(repo and repo.active_index_id)


async def _give_up(sessions: Sessions, job: Job, code: str) -> None:
    """Окончательный сбой: есть прежний индекс — отвечаем по нему, иначе статус error."""
    status = "ready" if await _has_index(sessions, job.repo_id) else "error"
    await _set_repo(sessions, job.repo_id, status=status, last_error=code[:60])
    await _finish(sessions, job.id, "failed", code)


async def process(sessions: Sessions, services: Services, job: Job) -> None:
    settings = get_settings()
    if job.repo_id is None:
        await _finish(sessions, job.id, "failed", "no_repo")
        return
    async with sessions() as s:
        repo = await s.get(Repository, job.repo_id)
    if repo is None:  # репозиторий отключили, пока задача ждала
        await _finish(sessions, job.id, "done")
        return

    try:
        if services.embeddings is None:
            raise LLMNotConfiguredError("gigachat")
        await index_repository(
            sessions,
            services.github,
            services.embeddings,
            job.repo_id,
            incremental=job.type == "index_update",
        )
    except GitHubAuthError:
        # Старый индекс остаётся доступным (FR-REPO-03).
        await _set_repo(sessions, job.repo_id, status="reauth_required", last_error="github_auth")
        await _finish(sessions, job.id, "failed", "github_auth")
    except (GitHubUnavailableError, LLMError, OSError) as exc:
        code = "github_unavailable" if isinstance(exc, GitHubUnavailableError) else str(
            getattr(exc, "code", type(exc).__name__)
        )
        permanent = isinstance(exc, LLMAuthError | LLMNotConfiguredError)
        if not permanent and job.attempts < settings.worker_max_attempts:
            delay = settings.worker_retry_base_sec * 2 ** (job.attempts - 1)
            await _set_repo(sessions, job.repo_id, last_error=code[:60])  # видно в статусе
            await _finish(sessions, job.id, "pending", code, retry_in=delay)
        else:
            await _give_up(sessions, job, code)
    except Exception as exc:  # noqa: BLE001 - ошибка индексации не должна ронять worker
        log.error("job %s failed: %s", job.id, type(exc).__name__)  # без текста: там могут быть данные
        await _give_up(sessions, job, type(exc).__name__)
    else:
        await _finish(sessions, job.id, "done")


async def run_pending(sessions: Sessions, services: Services, limit: int = 100) -> int:
    """Выполняет готовые к запуску задачи подряд. Возвращает, сколько обработано."""
    done = 0
    while done < limit and (job := await claim(sessions)) is not None:
        await process(sessions, services, job)
        done += 1
    return done
