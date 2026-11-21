"""Background jobs that survive a restart (FR-ADM-01/02, FR-ING-08): indexing, Git sync, FAQ recompute.

A job is a row in `rag_jobs`; the work runs in a background thread. Jobs that rebuild the knowledge base
run one at a time. On start-up, jobs that were queued or running when the process died are marked
`interrupted`; an interrupted indexing of a folder is started again, and if the project has no published
knowledge base yet, the bundled folder is indexed automatically (FR-ADM-02).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import sqlalchemy as sa

from . import db
from .config import get_settings
from .index import store
from .ingest.pipeline import collect_files, ingest
from .retrieval.kb import invalidate

log = logging.getLogger(__name__)
_ingest_lock = threading.Lock()
J = db.jobs


def get(job_id: str) -> dict | None:
    return db.one(sa.select(J).where(J.c.job_id == job_id))


def recent(limit: int = 20, project_id: str | None = None) -> list[dict]:
    q = sa.select(J)
    if project_id:
        q = q.where(J.c.project_id == project_id)
    return db.rows(q.order_by(J.c.created_at.desc()).limit(limit))


def _update(job_id: str, **values) -> None:
    db.execute(sa.update(J).where(J.c.job_id == job_id).values(**values))


def ingest_and_refresh(paths: list[str], project_id: str, describe: bool = True) -> dict:
    """Full rebuild of the knowledge base, then FAQ cache invalidation for the new generation (FR-FAQ-05)."""
    rep = ingest(paths, project_id, describe=describe)
    if rep.get("status") == "ok" and get_settings().faq_enabled:
        try:
            from .faq import get_faq

            rep["faq"] = get_faq().on_generation_change(project_id)
        except Exception as e:  # noqa: BLE001
            log.warning("faq invalidation failed: %s", e)
    return rep


def _run(job_id: str, project_id: str, fn: Callable[[], object], exclusive: bool) -> None:
    if exclusive and not _ingest_lock.acquire(blocking=False):
        _update(job_id, note="ждёт завершения предыдущей индексации")
        _ingest_lock.acquire()
    try:
        _update(job_id, status="running", started_at=time.time(), note=None)
        rep = fn()
        if isinstance(rep, dict):
            rep.pop("documents", None)
        ok = not isinstance(rep, dict) or rep.get("status") in ("ok", "up_to_date", None)
        _update(job_id, status="done" if ok else "failed", report=rep if isinstance(rep, (dict, list)) else None, finished_at=time.time())
        invalidate(project_id)
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", job_id)
        _update(job_id, status="failed", error=str(e)[:500], finished_at=time.time())
    finally:
        if exclusive:
            _ingest_lock.release()


def start_fn(kind: str, project_id: str, fn: Callable[[], object], wait: bool = False, exclusive: bool = True,
             params: dict | None = None) -> dict:
    """Run `fn` as a recorded background job. `params` are stored only for jobs that can be repeated from them."""
    job_id = uuid.uuid4().hex[:12]
    db.execute(sa.insert(J).values(job_id=job_id, kind=kind[:32], status="queued", project_id=project_id, params=params, created_at=time.time()))
    th = threading.Thread(target=_run, args=(job_id, project_id, fn, exclusive), daemon=True, name=f"job-{job_id}")
    th.start()
    if wait:
        th.join()
    return get(job_id) or {"job_id": job_id, "status": "queued"}


def start(kind: str, paths: list[str], project_id: str, describe: bool = True, wait: bool = False) -> dict:
    """Index a folder: the only kind of job that is repeated automatically after a restart."""
    paths = [str(p) for p in paths]
    return start_fn(kind, project_id, lambda: ingest_and_refresh(paths, project_id, describe), wait,
                    params={"paths": paths, "describe": describe})


def on_startup() -> list[dict]:
    """Recover unfinished jobs and index the bundled knowledge base when nothing is published yet."""
    s = get_settings()
    started: list[dict] = []
    stale = db.rows(sa.select(J).where(J.c.status.in_(["queued", "running"])).order_by(J.c.created_at))
    for job in stale:
        _update(job["job_id"], status="interrupted", finished_at=time.time(), note="сервис был перезапущен во время работы")
    repeatable = [j for j in stale if (j["params"] or {}).get("paths")]
    if repeatable and s.resume_jobs_on_start:
        last = repeatable[-1]  # indexing is idempotent: repeating the latest request covers the earlier ones
        p = last["params"]
        started.append(start(f"resume:{last['kind']}", p["paths"], last["project_id"], p.get("describe", True)))
    pid = s.default_project_id
    if not started and s.auto_index_on_start and not store.active_generation(pid):
        if Path(s.kb_dir).exists() and collect_files([s.kb_dir]):
            log.info("no published knowledge base for %r: indexing %s", pid, s.kb_dir)
            started.append(start("bootstrap", [s.kb_dir], pid))
        else:
            log.warning("no published knowledge base and no documents in %s", s.kb_dir)
    return started
