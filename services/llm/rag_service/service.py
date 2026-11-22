"""LLMGateway server side (FR-AGT-10, Miro D2.01–D2.14): ask(session_id, project_id, message, images?) → events.

Order: status «Ищу…» immediately → exact answer cache (level 1) → semantic FAQ cache (level 2, FR-FAQ-04)
(both only for self-contained questions) → AgentLoop → status… / delta… / final.
A cached answer is written into the session history (FR-FAQ-06), so a follow-up goes to the agent with context. Explicit operator requests are caught by Guardrails inside the loop.
"""

from __future__ import annotations

import contextvars
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Iterator

from .agent.input_guard import guard_turn
from .agent.loop import apply_hours_policy, format_answer, run_turn_stream
from .agent.memory import get_memory
from .analytics.query_logger import QueryLogger
from .analytics.questions import get_questions
from .cache import get_cache, is_cacheable_question, is_self_contained
from .core.config import get_settings
from .core.hours import get_schedule
from .faq import get_faq
from .index import store
from .retrieval import access

log = logging.getLogger(__name__)


def split_deltas(body: str) -> list[str]:
    return re.findall(r".{1,120}(?:\s|$)", body, re.S) or [body]


def ask_events(session_id: str, project_id: str | None, message: str, images: list[dict] | None = None,
               now: datetime | None = None, debug: bool = False,
               allowed_sections: list[str] | None = None, *, attachment_context: str = "") -> Iterator[dict]:
    """`allowed_sections` — sections the asking member may see (None = all). It is applied to the whole turn
    through a context variable; callers run this generator inside one Context (api/app.py)."""
    s = get_settings()
    project_id = project_id or s.default_project_id
    access.set_request_denied(access.denied_for_sections(project_id, allowed_sections))
    t0 = time.time()
    blocked = guard_turn(session_id, project_id, message)  # input guardrails (guard.py): refusal + hint, no agent call
    if blocked is not None:
        yield from blocked
        return
    yield {"type": "status", "text": "Ищу в документации…"}
    mem = get_memory()
    sess = mem.load(session_id, project_id)
    gen = store.active_generation(project_id)
    cacheable = bool(not attachment_context and s.answer_cache_enabled and gen and is_cacheable_question(
        message, bool(images), sess["turns"] == 0 or is_self_contained(message)))  # repeat mid-session → cache too
    if cacheable:
        hit = get_cache().lookup(project_id, gen, message, who=get_questions().person(session_id))
        level, extra = "exact", {}
        if not hit and s.faq_enabled:
            try:
                fh = get_faq().lookup(project_id, gen, message)
            except Exception as e:  # noqa: BLE001  (cache must never break answering)
                log.warning("faq lookup failed: %s", e)
                fh = None
            if fh:
                hit, level = fh["entry"]["answer"], "faq"
                extra = {"faq_entry_id": fh["entry"]["id"], "faq_score": fh["score"], "faq_question": fh["entry"]["question"],
                         "faq_origin": fh["entry"].get("origin")}
        if hit:
            yield from _serve_cached(hit, level, extra, sess, session_id, project_id, message, now, t0)
            return
    final = None
    first = True
    for ev in run_turn_stream(session_id, project_id, message, images, now=now, debug=debug,
                              attachment_context=attachment_context):
        if first and ev.get("type") == "status" and ev.get("text") == "Ищу в документации…":
            first = False
            continue
        first = False
        if ev.get("type") == "final":
            ev["cache_hit"] = False
            final = ev
        yield ev
    if cacheable and final:
        try:
            get_cache().store(project_id, gen, message, final)
        except Exception as e:  # noqa: BLE001
            log.warning("cache store failed: %s", e)


def _serve_cached(hit: dict, level: str, extra: dict, sess: dict, session_id: str, project_id: str, message: str,
                  now: datetime | None, t0: float) -> Iterator[dict]:
    res = {k: v for k, v in hit.items() if k not in ("cached_at", "question")}
    res.update({"cache_hit": True, "cache_level": level, **extra, "session_id": session_id, "project_id": project_id,
                "request_id": uuid.uuid4().hex[:16],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "llm_calls": 0, "by_model": {}, "cost_usd": 0.0, "cost_status": "known"},
                "tool_calls": 0, "search_calls": 0, "standalone": True})
    res.setdefault("buttons", [])
    apply_hours_policy(res, get_schedule().status(now))
    res["formatted_text"] = format_answer(res)
    res["latency_ms"] = res["first_token_ms"] = int((time.time() - t0) * 1000)
    # FR-FAQ-06: the cached Q&A becomes part of the session so follow-ups are handled by the agent with context
    sess["messages"] += [{"role": "user", "content": message},
                         {"role": "assistant", "content": res["text"], "action": "answer", "cache_hit": True,
                          "sources": [f"{x['source_id']}: {x['section_path']}" for x in res.get("sources", [])]}]
    sess["turns"] += 1
    get_memory().save(sess)
    QueryLogger().log_turn(project_id, session_id, res["request_id"], message, res | {"reason": "cache_hit"})
    if level == "faq" and extra.get("faq_entry_id"):
        try:
            get_faq().mark_served(project_id, extra["faq_entry_id"])
        except Exception:  # noqa: BLE001
            pass
    for part in split_deltas(res["formatted_text"]):
        yield {"type": "delta", "text": part}
    yield {"type": "final", **res}


def ask_sync(session_id: str, project_id: str | None, message: str, images: list[dict] | None = None,
             now: datetime | None = None, debug: bool = False, allowed_sections: list[str] | None = None, *,
             attachment_context: str = "") -> dict:
    # a private Context: the section restriction set by ask_events must not outlive this call
    return contextvars.copy_context().run(_ask_sync, session_id, project_id, message, images, now, debug,
                                          allowed_sections, attachment_context)


def _ask_sync(session_id, project_id, message, images, now, debug, allowed_sections, attachment_context) -> dict:
    statuses = []
    final: dict = {}
    for ev in ask_events(session_id, project_id, message, images, now, debug, allowed_sections,
                         attachment_context=attachment_context):
        if ev["type"] == "status":
            statuses.append(ev["text"])
        elif ev["type"] == "final":
            final = ev
    final["statuses"] = statuses
    return final
