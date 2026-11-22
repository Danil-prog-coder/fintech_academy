"""Knowledge-base management on the site, delegated to the RAG; finished jobs are announced as `docs.updated`."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.runtime import Core
from ..db.models import IndexJob, Project
from ..db.session import utc_now
from . import events
from .rag import RagError, RagUnavailable

log = logging.getLogger(__name__)
JOB_TIMEOUT = timedelta(hours=6)


async def track(session: AsyncSession, project: Project, job: dict | None, kind: str, summary: str | None) -> None:
    if job and job.get("job_id"):
        session.add(IndexJob(job_id=job["job_id"], project_id=project.id, kind=kind[:32], summary=(summary or "")[:500] or None))
        await session.commit()


async def follow_jobs(core: Core, session: AsyncSession) -> int:
    """Worker pass: ask the RAG about running jobs; a published new version is announced to the integration."""
    running = (await session.scalars(select(IndexJob).where(IndexJob.status == "running").limit(50))).all()
    announced = 0
    for job in running:
        project = await session.get(Project, job.project_id)
        if project is None:
            continue
        try:
            jobs = (await core.rag.jobs(project.rag_project_id, limit=50)).get("jobs", [])
        except (RagError, RagUnavailable) as e:
            log.debug("jobs of %s: %s", project.public_id, e)
            continue
        state = next((j for j in jobs if j.get("job_id") == job.job_id), None)
        if state is None and utc_now() - job.created_at > JOB_TIMEOUT:
            job.status, job.finished_at = "failed", utc_now()
            continue
        if state is None or state.get("status") in ("queued", "running"):
            continue
        rstatus = (state.get("report") or {}).get("status", "ok")
        ok = state.get("status") == "done" and rstatus in ("ok", "up_to_date", None)
        job.status, job.finished_at = ("done" if ok else "failed"), utc_now()
        if ok and rstatus != "up_to_date":  # nothing changed — nothing to announce
            report = state.get("report") or {}
            events.emit(session, project.integration_id, project.public_id, "docs.updated",
                        {"kind": job.kind, "summary": job.summary, "generation": report.get("generation"),
                         "counts": report.get("counts")})
            announced += 1
    await session.commit()
    return announced
