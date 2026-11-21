"""RAG service HTTP API (FR-AGT-10, FR-ADM-01/02/07, FR-AN-01..05, FR-FAQ-01..08, FR-GIT-01..07, FR-ESC-06, NFR-02).

Every endpoint except /health and the Git webhooks (which carry their own signature) needs
`Authorization: Bearer <token>`: the service token for the bot-facing part, the admin token for the panel.

Bot (service token):
POST /ask                  — SSE stream of contract events: status / delta / reset / final
POST /ask/sync             — same contract, one JSON (scripts, eval)
POST /transcribe           — a voice message → text (the bot then asks it as a question)
POST /sessions/{id}/reset  — /new
POST /feedback             — 👍/👎 for an answer, «эскалация была не нужна» for an escalation (FR-BOT-04, FR-ESC-08)
POST /knowledge            — a duty operator's answer becomes a knowledge-base document (FR-ESC-06)
GET  /images/{image_id}    — screenshot / diagram for image_ids from answers; crop=true — the highlighted element
GET  /documents            — documents of the active knowledge-base generation (+ /documents/{id}/outline)
GET  /faq/popular          — popular questions for the bot menu

Panel (admin token):
POST /documents, /reindex, /rollback, /cache/clear — knowledge base management
GET  /jobs, /jobs/{id}     — background jobs with reports; stored in the database, survive a restart
GET  /analytics/*          — metrics, time series, topics, requests + trace, doc places, gaps
GET  /analytics/clusters, /top-questions, /unanswered, /topics, /hot-answers, /answer-clusters — question clusters (api/questions.py)
/faq/*                     — frequent questions, semantic cache entries, recompute, manual management
/git/sources*              — Git repositories as a knowledge source
POST /webhooks/{github,gitlab} — push events, verified by signature / secret token

GET  /health               — liveness + dependencies (no token)
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import re
import logging
import shutil
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import __version__, confluence_control, confluence_source, db, doclinks, jobs
from ..agent.memory import get_memory
from ..analytics import report as an
from ..analytics import store as an_store
from ..analytics.classify import get_classifier
from ..analytics.questions import get_questions
from ..cache import get_cache
from ..config import get_settings
from ..faq import get_faq
from ..git_source import sources as git
from ..hours import get_schedule
from ..index import store
from ..ingest.pipeline import SUPPORTED
from ..knowledge import save_knowledge
from ..llm import LLMUnavailable
from ..project_paths import upload_dir, write_atomic
from ..retrieval.access import DEFAULT_SECTION, denied, doc_section
from ..retrieval.kb import get_kb, invalidate
from ..service import ask_events, ask_sync
from ..voice import AudioRejected, transcribe
from . import questions as questions_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("rag_service.api")


def _background_workers() -> None:
    """FR-AN-04 classifier, FR-FAQ-01 periodic recompute, FR-GIT-03 polling — all off the answer path."""
    s = get_settings()
    get_classifier().start_worker()
    get_questions().start_worker()
    git.start_poller(lambda sid: _start_fn_job("git_sync:poll", git.get(sid)["project_id"], lambda: git.sync(sid), False))
    if s.faq_enabled and s.faq_recompute_interval_s:
        def faq_loop():
            while True:
                time.sleep(s.faq_recompute_interval_s)
                try:
                    get_faq().recompute(s.default_project_id)
                except Exception as e:  # noqa: BLE001
                    log.warning("faq recompute: %s", e)
        threading.Thread(target=faq_loop, daemon=True, name="faq-recompute").start()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    s = get_settings()
    try:
        db.engine()
        # FR-ADM-02: interrupted indexing is repeated; an empty project gets the bundled knowledge base
        for job in await asyncio.to_thread(jobs.on_startup):
            log.info("job %s (%s) started on start-up", job.get("job_id"), job.get("kind"))
    except Exception:  # noqa: BLE001  (the API must come up even if recovery fails)
        log.exception("start-up recovery failed")
    if not s.auth_disabled and not (s.service_api_token or s.admin_api_token):
        log.warning("no API tokens configured: every endpoint except /health answers 503 until SERVICE_API_TOKEN / ADMIN_API_TOKEN are set")
    _background_workers()
    yield


app = FastAPI(title="BARS RAG service", version=__version__, lifespan=_lifespan)


# ------------------------------------------------------------------ auth (fail closed)
def _authorize(authorization: str | None, tokens: list[str]) -> None:
    s = get_settings()
    if s.auth_disabled:
        return
    tokens = [t for t in tokens if t]
    if not tokens:
        raise HTTPException(503, "API-токены не настроены: задайте SERVICE_API_TOKEN и ADMIN_API_TOKEN (или AUTH_DISABLED=true для локальной разработки)")
    if authorization not in {f"Bearer {t}" for t in tokens}:
        raise HTTPException(401, "нужен заголовок Authorization: Bearer <token>")


def service(authorization: str | None = Header(default=None)) -> None:
    """Bot-facing endpoints: the service token or the admin token."""
    s = get_settings()
    _authorize(authorization, [s.service_api_token, s.admin_api_token])


def admin(authorization: str | None = Header(default=None)) -> None:
    _authorize(authorization, [get_settings().admin_api_token])


app.include_router(questions_api.router, dependencies=[Depends(admin)])  # question clusters for the panel


# ------------------------------------------------------------------ ask
class ImageIn(BaseModel):
    mime: str = "image/png"
    data_base64: str


class AskIn(BaseModel):
    session_id: str
    project_id: str | None = None
    message: str = ""
    images: list[ImageIn] | None = None
    now: datetime | None = Field(default=None, description="override current time (demo of out-of-hours behaviour)")
    debug: bool = Field(default=False, description="include the full tool log (arguments and returned fragments) in `final`")
    user_ref: str | None = Field(default=None, max_length=64, description="optional salted hash of the user made by the caller "
                                 "(never a raw user id); counted only with QUESTION_USER_REF_ENABLED")
    allowed_sections: list[str] | None = Field(default=None, description="sections the asking member may see; null — all")


def _sse(ev: dict) -> str:
    return f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"


@app.post("/ask", dependencies=[Depends(service)])
async def ask(body: AskIn) -> StreamingResponse:
    imgs = [i.model_dump() for i in body.images] if body.images else None
    get_questions().remember_user(body.session_id, body.user_ref)
    gen = ask_events(body.session_id, body.project_id, body.message, imgs, body.now, body.debug, body.allowed_sections)
    loop = asyncio.get_running_loop()
    sentinel = object()
    ctx = contextvars.copy_context()  # one Context for the whole turn: the section restriction lives there

    async def stream():
        while True:
            ev = await loop.run_in_executor(None, ctx.run, next, gen, sentinel)
            if ev is sentinel:
                break
            yield _sse(ev)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/ask/sync", dependencies=[Depends(service)])
async def ask_json(body: AskIn) -> dict:
    imgs = [i.model_dump() for i in body.images] if body.images else None
    get_questions().remember_user(body.session_id, body.user_ref)
    return await asyncio.to_thread(ask_sync, body.session_id, body.project_id, body.message, imgs, body.now, body.debug,
                                   body.allowed_sections)


class TranscribeIn(BaseModel):
    mime: str = "audio/ogg"
    data_base64: str


@app.post("/transcribe", dependencies=[Depends(service)])
async def transcribe_audio(body: TranscribeIn) -> dict:
    """Voice message → {"text", "model"}: 422 — the file cannot be read, 503 — no model could transcribe it."""
    try:
        return await asyncio.to_thread(transcribe, body.data_base64, body.mime)
    except AudioRejected as e:
        raise HTTPException(422, str(e)) from e
    except (LLMUnavailable, TimeoutError) as e:
        log.warning("transcription failed: %s", e)
        raise HTTPException(503, "распознавание речи сейчас недоступно") from e


@app.post("/sessions/{session_id}/reset", dependencies=[Depends(service)])
def reset(session_id: str, project_id: str | None = None) -> dict:
    get_memory().reset(session_id, project_id or get_settings().default_project_id)
    return {"ok": True}


# ------------------------------------------------------------------ documents / indexing jobs
def _start_fn_job(kind: str, project_id: str, fn, wait: bool, exclusive: bool = True) -> dict:
    return jobs.start_fn(kind, project_id, fn, wait, exclusive)


def _start_job(kind: str, paths: list[str], project_id: str, describe: bool, wait: bool) -> dict:
    return jobs.start(kind, paths, project_id, describe, wait)


@app.get("/documents", dependencies=[Depends(service)])
def documents(project_id: str | None = None) -> dict:
    pid = project_id or get_settings().default_project_id
    m = store.active_manifest(pid)
    blocked = denied(pid, m)
    docs = [{**{k: d.get(k) for k in ("doc_id", "title", "file", "source_type", "document_version", "sections", "chunks",
                                      "chunk_types", "tables", "images", "images_described", "images_broken", "git")},
             "section": doc_section(d)}
            for d in m.get("documents", []) if d["doc_id"] not in blocked]
    return {"project_id": pid, "generation": m.get("generation"), "published_at": m.get("created_at"),
            "embedding_model": m.get("embedding_model"), "counts": m.get("counts"), "documents": docs}


@app.get("/documents/{doc_id}/outline", dependencies=[Depends(service)])
def outline(doc_id: str, project_id: str | None = None) -> dict:
    pid = project_id or get_settings().default_project_id
    m = store.active_manifest(pid)
    for d in m.get("documents", []):
        if d["doc_id"] == doc_id and doc_id not in denied(pid, m):
            return {"doc_id": doc_id, "title": d["title"], "outline": d.get("outline", [])}
    raise HTTPException(404, "document not found")


def _doc_access(doc_id: str, project_id: str | None, sig: str | None, authorization: str | None) -> tuple[str, dict]:
    """FR-GEN-02: a signed link (from the bot's sources block) or the service token opens a document of the project."""
    s = get_settings()
    pid = project_id or s.default_project_id
    if not doclinks.verify(s, pid, doc_id, sig):
        _authorize(authorization, [s.service_api_token, s.admin_api_token])
    m = store.active_manifest(pid)
    doc = next((d for d in m.get("documents", []) if d["doc_id"] == doc_id and doc_id not in denied(pid, m)), None)
    if doc is None:
        raise HTTPException(404, "document not found")
    return pid, doc


@app.get("/documents/{doc_id}/view", response_class=HTMLResponse)
def document_view(doc_id: str, project_id: str | None = None, sig: str | None = None,
                  authorization: str | None = Header(default=None)) -> HTMLResponse:
    """The indexed document as HTML with an anchor per section (`#sec-2.4.6`) — target of source links (FR-GEN-02)."""
    pid, doc = _doc_access(doc_id, project_id, sig, authorization)
    chunks = [c for c in get_kb(pid)["chunks"] if c["doc_id"] == doc_id]
    q = f"project_id={quote(pid)}" + (f"&sig={quote(sig)}" if sig else "")
    page = doclinks.render_view(doc, chunks, lambda iid: f"view/img/{quote(iid)}?{q}")
    return HTMLResponse(page, headers={"Cache-Control": "private, max-age=300", "X-Robots-Tag": "noindex"})


@app.get("/documents/{doc_id}/view/img/{image_id:path}")
def document_view_image(doc_id: str, image_id: str, project_id: str | None = None, sig: str | None = None,
                        authorization: str | None = Header(default=None)) -> FileResponse:
    pid, _doc = _doc_access(doc_id, project_id, sig, authorization)
    info = get_kb(pid)["images"].get(image_id)
    p = _image_path(get_settings(), info or {})
    if not info or not image_id.startswith(doc_id + "/") or not p.is_file():
        raise HTTPException(404, "image not found")
    return FileResponse(p)


@app.get("/documents/{doc_id}/file")
def document_file(doc_id: str, project_id: str | None = None, sig: str | None = None,
                  authorization: str | None = Header(default=None)) -> FileResponse:
    """The uploaded original (PDF links add `#page=N`); Git documents link to the repository instead."""
    pid, doc = _doc_access(doc_id, project_id, sig, authorization)
    f = doclinks.original_file(get_settings(), doc, pid)
    if f is None:
        raise HTTPException(404, "original file not available")
    return FileResponse(f, filename=f.name, content_disposition_type="inline")


SECTION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def _section_dir(kb: Path, section: str) -> Path:
    if not SECTION_RE.match(section):
        raise HTTPException(422, "раздел: латиница в нижнем регистре, цифры, «-» и «_», до 40 символов")
    return kb / section


def _staged_files(kb: Path) -> list[Path]:
    return sorted(p for p in kb.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED and "images" not in p.parts)


@app.post("/documents", dependencies=[Depends(admin)])
async def upload(files: list[UploadFile] = File(...), mode: Literal["append", "replace"] = Form("append"),
                 project_id: str | None = Form(None), section: str = Form(DEFAULT_SECTION),
                 describe_images: bool = Form(True), wait: bool = Form(False), index: bool = Form(False)) -> dict:
    """Files go to `<project>/<section>/`. `replace` replaces one section, never the whole project.

    A document is identified by its file name (doc_id = slug of the name), so the same name in another section
    of the project is a conflict (409), not a silent overwrite."""
    s = get_settings()
    pid = project_id or s.default_project_id
    kb = upload_dir(s, pid)
    target = _section_dir(kb, section)
    bad = [f.filename for f in files if Path(f.filename or "").suffix.lower() not in SUPPORTED]
    if bad:
        raise HTTPException(415, f"неподдерживаемый формат: {bad}; поддерживаются {sorted(SUPPORTED)}")
    names = [Path(f.filename or "").name for f in files]
    others = {p.stem.lower(): p for p in _staged_files(kb) if p.parent != target}
    clash = [n for n in names if Path(n).stem.lower() in others]
    if clash:
        raise HTTPException(409, f"документ с таким именем уже есть в другом разделе: {clash}")
    target.mkdir(parents=True, exist_ok=True)
    if mode == "replace":
        backup = kb.parent / f"{kb.name}_backup_{time.strftime('%Y%m%d%H%M%S')}" / section
        shutil.copytree(target, backup, dirs_exist_ok=True)
        for p in target.iterdir():
            if p.is_file() and p.suffix.lower() in SUPPORTED:
                p.unlink()
    saved = []
    for f in files:
        dest = target / Path(f.filename).name
        await asyncio.to_thread(write_atomic, dest, await f.read())
        saved.append(dest.name)
    if not index:
        return {"saved": saved, "section": section, "job": None, "status": "staged", "published": False}
    job = await asyncio.to_thread(_start_job, f"upload:{mode}", [str(kb)], pid, describe_images, wait)
    return {"saved": saved, "section": section, "job": job}


@app.get("/documents/staged", dependencies=[Depends(admin)])
def staged(project_id: str | None = None) -> dict:
    """Files waiting in the project folder (published or not): what the next reindex will index."""
    s = get_settings()
    kb = upload_dir(s, project_id or s.default_project_id)
    files = _staged_files(kb) if kb.exists() else []
    return {"files": [{"name": p.name, "section": p.parent.name if p.parent != kb else DEFAULT_SECTION,
                       "size": p.stat().st_size, "modified_at": p.stat().st_mtime} for p in files]}


@app.delete("/documents/{doc_id}", dependencies=[Depends(admin)])
async def delete_document(doc_id: str, project_id: str | None = None, wait: bool = False) -> dict:
    """Remove the uploaded original of a document and publish a new generation without it."""
    s = get_settings()
    pid = project_id or s.default_project_id
    kb = upload_dir(s, pid)
    from ..ingest.util import slugify

    victims = [p for p in (_staged_files(kb) if kb.exists() else []) if slugify(p.stem) == doc_id or p.name == doc_id]
    if not victims:
        raise HTTPException(404, "document not found")
    for p in victims:
        p.unlink()
    job = await asyncio.to_thread(_start_job, "delete", [str(kb)], pid, True, wait)
    return {"deleted": [p.name for p in victims], "job": job}


class ReindexIn(BaseModel):
    project_id: str | None = None
    describe_images: bool = True
    wait: bool = False


@app.post("/reindex", dependencies=[Depends(admin)])
async def reindex(body: ReindexIn | None = None) -> dict:
    body = body or ReindexIn()
    s = get_settings()
    pid = body.project_id or s.default_project_id
    return await asyncio.to_thread(_start_job, "reindex", [str(upload_dir(s, pid))], pid, body.describe_images, body.wait)


@app.get("/jobs", dependencies=[Depends(admin)])
def job_list(limit: int = 20) -> dict:
    return {"jobs": jobs.recent(min(limit, 100))}


@app.get("/jobs/{job_id}", dependencies=[Depends(admin)])
def job(job_id: str) -> dict:
    j = jobs.get(job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    if str(j.get("kind") or "").startswith("confluence"):
        # the Confluence adapter polls this job and accepts only pending | running | done | error
        return {**j, **confluence_source.contract_job(j)}
    return j


@app.post("/sources/{source_id}/batches", dependencies=[Depends(admin)])
async def confluence_batch(source_id: str, request: Request) -> dict:
    """Import Confluence to staging; accepted means stored, never published (FR-ADM-09)."""
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "invalid JSON") from None
    try:
        return await asyncio.to_thread(confluence_source.receive_batch, source_id, body, None)
    except confluence_source.BatchError as e:
        raise HTTPException(422 if e.unknown_source else 400, str(e)) from None


@app.get("/sources/staging", dependencies=[Depends(admin)])
def confluence_staging(project_id: str | None = None) -> dict:
    pid = project_id or get_settings().default_project_id
    return confluence_source.staging_status(pid, store.active_manifest(pid))


@app.get("/confluence/sources", dependencies=[Depends(admin)])
async def confluence_sources(project_id: str | None = None) -> dict:
    pid = project_id or get_settings().default_project_id
    try:
        return await asyncio.to_thread(confluence_control.list_sources, pid)
    except confluence_control.ControlUnavailable as error:
        raise HTTPException(503, str(error)) from None


class ConfluenceImportIn(BaseModel):
    project_id: str
    page_url: str = Field(default="", max_length=2048)


class ConfluenceRegisterIn(BaseModel):
    project_id: str
    template_source_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    page_url: str = Field(min_length=1, max_length=2048)
    include_children: bool = True


@app.post("/confluence/sources", dependencies=[Depends(admin)])
async def register_confluence_source(body: ConfluenceRegisterIn) -> dict:
    template = confluence_source.allowed_sources().get(body.template_source_id)
    if not template or template.get("managed") or template.get("project_id") != body.project_id:
        raise HTTPException(404, "source template not found in this project")
    try:
        return await asyncio.to_thread(confluence_control.register_source, body.project_id,
                                       body.template_source_id, body.page_url, body.include_children)
    except confluence_control.ControlRejected as error:
        raise HTTPException(error.status_code, str(error)) from None
    except confluence_control.ControlUnavailable as error:
        raise HTTPException(503, str(error)) from None


@app.post("/confluence/sources/{source_id}/sync", dependencies=[Depends(admin)])
async def confluence_import(source_id: str, body: ConfluenceImportIn) -> dict:
    src = confluence_source.allowed_sources().get(source_id)
    if not src or src.get("project_id") != body.project_id:
        raise HTTPException(404, "source not found in this project")
    return jobs.start_fn("confluence-import", body.project_id,
                         lambda: confluence_control.import_source(body.project_id, source_id, body.page_url),
                         exclusive=False)


@app.post("/rollback", dependencies=[Depends(admin)])
def rollback(project_id: str | None = None) -> dict:
    pid = project_id or get_settings().default_project_id
    gen = store.rollback(pid)
    invalidate(pid)
    if not gen:
        raise HTTPException(409, "нет предыдущей версии базы")
    return {"active_generation": gen, "faq": get_faq().on_generation_change(pid)}  # FR-FAQ-05


@app.post("/cache/clear", dependencies=[Depends(admin)])
def cache_clear(project_id: str | None = None, level: Literal["exact", "faq", "all"] = "exact") -> dict:
    """level=exact — level-1 cache; faq — auto FAQ entries (manual ones are kept); all — both."""
    pid = project_id or get_settings().default_project_id
    out = {}
    if level in ("exact", "all"):
        out["deleted"] = get_cache().clear(pid)
    if level in ("faq", "all"):
        out["faq_deleted"] = get_faq().clear(pid)
    return out


@app.get("/images", dependencies=[Depends(admin)])
def image_list(project_id: str | None = None) -> dict:
    """Images of the active knowledge base with the text the index holds for each (FR-ING-04).

    `text` is the image chunk the agent finds and reads (the vision model's description and the labels it read);
    `model` is the model that wrote it. Used to check descriptions against a reference (`rag_eval images`)."""
    kb = get_kb(project_id or get_settings().default_project_id)
    chunk_of: dict[str, dict] = {}
    for c in kb["chunks"]:
        if c.get("chunk_type") == "image":
            for iid in c.get("image_ids") or []:
                chunk_of.setdefault(iid, c)
    items = []
    for iid, info in kb["images"].items():
        c = chunk_of.get(iid) or {}
        items.append({
            "image_id": iid, "kind": info.get("kind"), "title": info.get("title"), "broken": bool(info.get("broken")),
            "model": info.get("model") or None, "has_crop": bool(info.get("crop_path")),
            "document_title": c.get("document_title"), "section_path": " → ".join(c.get("section_path") or []) or None,
            "page": c.get("page"), "description": info.get("description") or "", "ocr_text": info.get("ocr_text") or "",
            "text": c.get("text") or "",
        })
    return {"generation": kb["generation"], "images": items}


@app.get("/images/user/{name}", dependencies=[Depends(service)])
def user_image(name: str) -> FileResponse:
    """FR-VIS-03: the user's screenshot attached to an escalation card (user_image_ids)."""
    p = Path(get_settings().state_dir) / "user_images" / Path(name).name
    if not p.exists():
        raise HTTPException(404, "image not found")
    return FileResponse(p)


def _image_path(s, info: dict) -> Path:
    p = Path(info.get("path") or "")
    if not p.exists():  # paths are stored absolute at ingest time; resolve relative to KB/state dirs (docker)
        for base in (Path(s.kb_dir), Path(s.state_dir)):
            for marker in ("/data/kb/", "/var/"):
                if marker in p.as_posix():
                    cand = base / p.as_posix().split(marker, 1)[1]
                    if cand.exists():
                        p = cand
                        break
            if p.exists():
                break
    return p


@app.get("/images/{image_id:path}", dependencies=[Depends(service)])
def image(image_id: str, project_id: str | None = None, crop: bool = False) -> FileResponse:
    """crop=true — the cut-out of the element highlighted with a frame, if the screenshot has one (FR-ING-06)."""
    s = get_settings()
    pid = project_id or s.default_project_id
    info = get_kb(pid)["images"].get(image_id)
    if not info:
        raise HTTPException(404, "image not found")
    p = _image_path(s, info)
    if not p.exists():
        raise HTTPException(404, "image file missing")
    if crop:
        from ..ingest.crops import crop_red_frame

        cp = Path(info.get("crop_path") or "")
        if not cp.exists():
            cp = Path(s.state_dir) / "image_crops" / f"{image_id}.png"
            if not cp.exists() and not crop_red_frame(p, cp):
                cp = None
        if cp:
            return FileResponse(cp)
    return FileResponse(p)


# ------------------------------------------------------------------ analytics (FR-AN-01..05)
@app.get("/analytics/summary", dependencies=[Depends(admin)])
def analytics(days: int = 7, project_id: str | None = None) -> dict:
    """FR-AN-02: requests per day/week, success rate, escalations, latency, topics, cache savings, 👍/👎."""
    return an.summary(days, project_id)


@app.get("/analytics/timeseries", dependencies=[Depends(admin)])
def analytics_timeseries(days: int = 7, bucket: Literal["day", "hour"] = "day", project_id: str | None = None) -> dict:
    return an.timeseries(days, bucket, project_id)


@app.get("/analytics/distribution", dependencies=[Depends(admin)])
def analytics_distribution(days: int = 30, project_id: str | None = None) -> dict:
    return an.distribution(days, project_id)


@app.get("/analytics/requests", dependencies=[Depends(admin)])
def analytics_requests(days: int = 7, limit: int = 50, action: str | None = None, project_id: str | None = None) -> list[dict]:
    return an.requests(days, limit, action, project_id)


@app.get("/analytics/requests/{request_id}", dependencies=[Depends(admin)])
def analytics_request(request_id: str) -> dict:
    d = an.request_detail(request_id)
    if not d:
        raise HTTPException(404, "request not found")
    return d


@app.get("/analytics/doc-sections", dependencies=[Depends(admin)])
def analytics_doc_sections(days: int = 30, project_id: str | None = None) -> dict:
    return an.doc_sections(days, project_id)


@app.get("/analytics/gaps", dependencies=[Depends(admin)])
def analytics_gaps(days: int = 30, project_id: str | None = None) -> dict:
    """FR-AN-05: clusters of unanswered / 👎 questions — what the documentation is missing."""
    return an.gaps(days, project_id)


@app.get("/analytics/dashboard", dependencies=[Depends(admin)])
def analytics_dashboard(days: int = 7, project_id: str | None = None) -> dict:
    """FR-AN-03: everything the admin dashboard screen needs in one call."""
    pid = project_id or get_settings().default_project_id
    return {"summary": an.summary(days, pid), "timeseries_day": an.timeseries(days, "day", pid),
            "timeseries_hour": an.timeseries(1, "hour", pid), "distribution": an.distribution(max(days, 7), pid),
            "faq": get_faq().stats(pid), "recent": an.requests(days, 20, None, pid)}


class ClassifyIn(BaseModel):
    days: int = 30
    limit: int = 200
    use_llm: bool = True


@app.post("/analytics/classify", dependencies=[Depends(admin)])
async def analytics_classify(body: ClassifyIn | None = None) -> dict:
    """FR-AN-04: classify unclassified requests now (normally a background worker does it)."""
    b = body or ClassifyIn()
    return await asyncio.to_thread(get_classifier().run, b.days, b.limit, b.use_llm)


@app.get("/analytics/taxonomy", dependencies=[Depends(admin)])
def taxonomy() -> dict:
    return get_classifier().taxonomy()


class TaxonomyIn(BaseModel):
    topics: list[str]


@app.put("/analytics/taxonomy", dependencies=[Depends(admin)])
def taxonomy_put(body: TaxonomyIn) -> dict:
    tx = get_classifier().taxonomy()
    tx["topics"] = list(dict.fromkeys(t.strip() for t in body.topics if t.strip()))
    return get_classifier().save_taxonomy(tx)


@app.post("/analytics/taxonomy/candidates/{name}/accept", dependencies=[Depends(admin)])
def taxonomy_accept(name: str) -> dict:
    return get_classifier().accept_candidate(name)


# ------------------------------------------------------------------ feedback (FR-BOT-04, FR-ESC-08)
class FeedbackIn(BaseModel):
    request_id: str
    rating: Literal["up", "down"] | None = None
    escalation_unneeded: bool | None = Field(default=None, description="the duty operator's «Эскалация была не нужна» mark")
    session_id: str | None = None
    comment: str | None = Field(default=None, max_length=2000)


@app.post("/feedback", dependencies=[Depends(service)])
def feedback(body: FeedbackIn) -> dict:
    if body.rating is None and body.escalation_unneeded is None:
        raise HTTPException(422, "нужно поле rating или escalation_unneeded")
    turn = an_store.find_turn(body.request_id, days=30)
    if not turn:
        raise HTTPException(404, "request not found")
    out: dict[str, Any] = {"ok": True}
    if body.escalation_unneeded is not None:
        an_store.record_escalation_unneeded(body.request_id, body.escalation_unneeded, body.comment)
    if body.rating is None:
        return out
    an_store.record_feedback(body.request_id, body.rating, body.session_id, body.comment)
    if turn.get("faq_entry_id"):  # FR-FAQ-05: 👎 on a cached answer counts against the entry
        e = get_faq().feedback(turn.get("project_id") or get_settings().default_project_id, turn["faq_entry_id"], body.rating)
        out["faq_entry"] = {"id": e["id"], "enabled": e["enabled"], "dislikes": e.get("dislikes")} if e else None
    if body.rating == "down":
        out["offer_operator"] = True  # FR-BOT-04: 👎 offers an escalation
    return out


# ------------------------------------------------------------------ operators' answers → knowledge base (FR-ESC-06)
class KnowledgeIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    answer: str = Field(min_length=3, max_length=20000)
    author: str | None = Field(default=None, max_length=128)
    project_id: str | None = None
    section: str | None = Field(default=None, max_length=40)
    wait: bool = False


@app.post("/knowledge", dependencies=[Depends(service)])
async def knowledge(body: KnowledgeIn) -> dict:
    """The answer is saved as a document «Ответ поддержки, <дата>» and indexed like any other document."""
    if body.section is not None and not SECTION_RE.match(body.section):
        raise HTTPException(422, "недопустимое имя раздела")
    return await asyncio.to_thread(save_knowledge, body.project_id or get_settings().default_project_id,
                                   body.question, body.answer, body.author, body.wait, body.section)


# ------------------------------------------------------------------ FAQ (FR-FAQ-01..08)
def _pid(project_id: str | None) -> str:
    return project_id or get_settings().default_project_id


@app.get("/faq/stats", dependencies=[Depends(admin)])
def faq_stats(project_id: str | None = None) -> dict:
    """FR-FAQ-02: top-K with counts, trend, paraphrases, topic, outcomes, 👍/👎, documentation places, highlights."""
    return get_faq().stats(_pid(project_id))


@app.get("/faq/popular", dependencies=[Depends(service)])
def faq_popular(limit: int = 5, project_id: str | None = None) -> dict:
    """FR-FAQ-07: popular questions for the bot menu / greeting."""
    return {"questions": get_faq().popular(_pid(project_id), limit)}


class RecomputeIn(BaseModel):
    project_id: str | None = None
    build: bool = True
    days: int | None = None
    top_k: int | None = None
    wait: bool = False


@app.post("/faq/recompute", dependencies=[Depends(admin)])
async def faq_recompute(body: RecomputeIn | None = None) -> dict:
    """FR-FAQ-01/03/05: re-cluster, rebuild answers for the top-K, drop stale auto entries (background job)."""
    b = body or RecomputeIn()
    pid = _pid(b.project_id)
    return await asyncio.to_thread(_start_fn_job, "faq_recompute", pid,
                                   lambda: get_faq().recompute(pid, build=b.build, days=b.days, top_k=b.top_k), b.wait, False)


@app.get("/faq/entries", dependencies=[Depends(admin)])
def faq_entries(project_id: str | None = None) -> list[dict]:
    return get_faq().list_entries(_pid(project_id))


@app.get("/faq/entries/{entry_id}", dependencies=[Depends(admin)])
def faq_entry(entry_id: str, project_id: str | None = None) -> dict:
    e = get_faq().get_entry(_pid(project_id), entry_id)
    if not e:
        raise HTTPException(404, "entry not found")
    return e


class FaqSource(BaseModel):
    document_title: str
    section_path: str | None = None
    chunk_id: str | None = None
    doc_id: str | None = None
    excerpt: str | None = None
    image_ids: list[str] | None = None
    url: str | None = None


class FaqEntryIn(BaseModel):
    question: str
    text: str
    paraphrases: list[str] | None = None
    sources: list[FaqSource] | None = None
    support_answer: bool = False  # «Ответ поддержки» without a documentation link (FR-ESC-06)
    by: str | None = None
    project_id: str | None = None


@app.post("/faq/entries", dependencies=[Depends(admin)])
async def faq_create(body: FaqEntryIn) -> dict:
    """FR-FAQ-08: manual entry; works immediately, warns about similar existing questions."""
    if not body.sources and not body.support_answer:
        raise HTTPException(422, "нужны источники (sources) или support_answer=true")
    return await asyncio.to_thread(get_faq().create_manual, _pid(body.project_id), body.question, body.text,
                                   paraphrases=body.paraphrases, sources=[x.model_dump() for x in body.sources or []],
                                   support_answer=body.support_answer, by=body.by)


class FaqEditIn(BaseModel):
    question: str | None = None
    text: str | None = None
    paraphrases: list[str] | None = None
    sources: list[FaqSource] | None = None
    enabled: bool | None = None
    by: str | None = None


@app.patch("/faq/entries/{entry_id}", dependencies=[Depends(admin)])
async def faq_edit(entry_id: str, body: FaqEditIn, project_id: str | None = None) -> dict:
    """FR-FAQ-08: edit → origin=manual, never overwritten automatically; enabled=true re-activates a reviewed entry."""
    e = await asyncio.to_thread(get_faq().edit, _pid(project_id), entry_id, text=body.text, question=body.question,
                                sources=[x.model_dump() for x in body.sources] if body.sources is not None else None,
                                paraphrases=body.paraphrases, enabled=body.enabled, by=body.by)
    if not e:
        raise HTTPException(404, "entry not found")
    return e


@app.delete("/faq/entries/{entry_id}", dependencies=[Depends(admin)])
def faq_delete(entry_id: str, no_cache: bool = False, project_id: str | None = None, by: str | None = None) -> dict:
    """«Удалить» / «Удалить и не кэшировать» (no_cache=true → stop-list)."""
    if not get_faq().delete(_pid(project_id), entry_id, no_cache=no_cache, by=by):
        raise HTTPException(404, "entry not found")
    return {"ok": True, "stoplisted": no_cache}


@app.get("/faq/entries/{entry_id}/history", dependencies=[Depends(admin)])
def faq_history(entry_id: str, project_id: str | None = None) -> list[dict]:
    return get_faq().history(_pid(project_id), entry_id)


class RestoreIn(BaseModel):
    version: int
    by: str | None = None


@app.post("/faq/entries/{entry_id}/restore", dependencies=[Depends(admin)])
async def faq_restore(entry_id: str, body: RestoreIn, project_id: str | None = None) -> dict:
    e = await asyncio.to_thread(get_faq().restore, _pid(project_id), entry_id, body.version, body.by)
    if not e:
        raise HTTPException(404, "version not found")
    return e


@app.delete("/faq/stoplist/{stop_id}", dependencies=[Depends(admin)])
def faq_unstop(stop_id: str, project_id: str | None = None) -> dict:
    if not get_faq().unstop(_pid(project_id), stop_id):
        raise HTTPException(404, "not in stop-list")
    return {"ok": True}


# ------------------------------------------------------------------ Git sources (FR-GIT-01..07)
class GitSourceIn(BaseModel):
    provider: Literal["github", "gitlab"]
    repo: str = Field(description="owner/name (GitLab: group/subgroup/name)")
    branch: str = "main"
    base_url: str | None = Field(default=None, description="self-hosted GitLab / GitHub Enterprise base URL")
    include: list[str] | None = Field(default=None, description="glob patterns, e.g. docs/**/*.md")
    exclude: list[str] | None = None
    token_env: str | None = Field(default=None, description="NAME of the env variable with a read-only token (FR-GIT-07)")
    project_id: str | None = None
    sync: bool = True
    wait: bool = False


@app.get("/git/sources", dependencies=[Depends(admin)])
def git_sources(project_id: str | None = None) -> list[dict]:
    return [git.public_view(x) for x in git.load_all().values() if not project_id or x["project_id"] == project_id]


@app.post("/git/sources", dependencies=[Depends(admin)])
async def git_add(body: GitSourceIn) -> dict:
    try:
        src = git.add(_pid(body.project_id), body.provider, body.repo, body.branch, base_url=body.base_url,
                      include=body.include, exclude=body.exclude, token_env=body.token_env)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    out = {"source": git.public_view(src, with_secret=True)}
    if body.sync:
        out["job"] = await asyncio.to_thread(_start_fn_job, "git_sync:full", src["project_id"], lambda: git.sync(src["id"], full=True), body.wait)
    return out


@app.get("/git/sources/{source_id}", dependencies=[Depends(admin)])
def git_get(source_id: str, show_secret: bool = False) -> dict:
    src = git.get(source_id)
    if not src:
        raise HTTPException(404, "source not found")
    return git.public_view(src, with_secret=show_secret)


class GitPatchIn(BaseModel):
    branch: str | None = None
    include: list[str] | None = None
    exclude: list[str] | None = None
    token_env: str | None = None
    enabled: bool | None = None
    base_url: str | None = None


@app.patch("/git/sources/{source_id}", dependencies=[Depends(admin)])
def git_patch(source_id: str, body: GitPatchIn) -> dict:
    try:
        src = git.update(source_id, **body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    if not src:
        raise HTTPException(404, "source not found")
    return git.public_view(src)


@app.delete("/git/sources/{source_id}", dependencies=[Depends(admin)])
async def git_delete(source_id: str, wait: bool = True) -> dict:
    src = git.get(source_id)
    if not src:
        raise HTTPException(404, "source not found")
    return await asyncio.to_thread(_start_fn_job, "git_remove", src["project_id"], lambda: git.remove(source_id), wait)


@app.post("/git/sources/{source_id}/check", dependencies=[Depends(admin)])
async def git_check(source_id: str) -> dict:
    if not git.get(source_id):
        raise HTTPException(404, "source not found")
    return await asyncio.to_thread(git.check_access, source_id)


class GitSyncIn(BaseModel):
    full: bool = False
    describe_images: bool = True
    wait: bool = False


@app.post("/git/sources/{source_id}/sync", dependencies=[Depends(admin)])
async def git_sync(source_id: str, body: GitSyncIn | None = None) -> dict:
    """«Синхронизировать»: incremental by commit diff (full=true — full re-import)."""
    b = body or GitSyncIn()
    src = git.get(source_id)
    if not src:
        raise HTTPException(404, "source not found")
    return await asyncio.to_thread(_start_fn_job, f"git_sync:{'full' if b.full else 'incremental'}", src["project_id"],
                                   lambda: git.sync(source_id, full=b.full, describe=b.describe_images), b.wait)


@app.post("/webhooks/github")
async def webhook_github(request: Request) -> dict:
    """FR-GIT-03/07: push event; the X-Hub-Signature-256 HMAC is mandatory."""
    body = await request.body()
    if request.headers.get("X-GitHub-Event", "push") == "ping":
        return {"ok": True, "pong": True}
    try:
        ev = json.loads(body)
        repo, ref = ev["repository"]["full_name"], ev.get("ref", "")
    except (ValueError, KeyError):
        raise HTTPException(400, "bad payload") from None
    cands = git.sources_for_push("github", repo, ref)
    srcs = [x for x in cands if git.verify_github(x["webhook_secret"], body, request.headers.get("X-Hub-Signature-256"))]
    if cands and not srcs:
        raise HTTPException(401, "bad signature")
    jobs = [_start_fn_job("git_sync:webhook", x["project_id"], (lambda sid=x["id"]: git.sync(sid)), False)["job_id"] for x in srcs]
    return {"ok": True, "jobs": jobs}


@app.post("/webhooks/gitlab")
async def webhook_gitlab(request: Request) -> dict:
    body = await request.body()
    try:
        ev = json.loads(body)
        repo, ref = ev["project"]["path_with_namespace"], ev.get("ref", "")
    except (ValueError, KeyError):
        raise HTTPException(400, "bad payload") from None
    cands = git.sources_for_push("gitlab", repo, ref)
    srcs = [x for x in cands if git.verify_gitlab(x["webhook_secret"], request.headers.get("X-Gitlab-Token"))]
    if cands and not srcs:
        raise HTTPException(401, "bad token")
    jobs = [_start_fn_job("git_sync:webhook", x["project_id"], (lambda sid=x["id"]: git.sync(sid)), False)["job_id"] for x in srcs]
    return {"ok": True, "jobs": jobs}


# ------------------------------------------------------------------ health
@app.get("/health")
def health() -> dict:
    s = get_settings()
    out: dict[str, Any] = {"status": "ok", "version": __version__}
    try:
        store.get_client().get_collections()
        out["qdrant"] = "server" if s.qdrant_url else "local"
    except Exception as e:  # noqa: BLE001
        out["status"], out["qdrant"] = "degraded", f"error: {e}"[:200]
    mem = get_memory()
    out["redis"] = mem.backend if mem.ping() else "error"
    out["database"] = ("postgres" if (s.database_url or "").startswith("postgres") else "sqlite") if db.ping() else "error"
    if out["database"] == "error":
        out["status"] = "degraded"
    out["auth"] = "disabled" if s.auth_disabled else ("configured" if (s.service_api_token or s.admin_api_token) else "missing")
    out["active_generation"] = store.active_generation(s.default_project_id)
    out["agent_model"] = s.agent_model
    out["support"] = get_schedule().status()
    return out
