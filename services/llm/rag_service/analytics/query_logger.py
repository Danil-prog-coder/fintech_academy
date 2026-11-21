"""QueryLogger (FR-AN-01, FR-AGT-05, FR-AGT-08): one row per turn with the agent trace, tokens and cost.

Turns are stored in the relational database (`rag_turns`, see rag_service/db.py), not in files.
152-ФЗ / NFR-05: session ids are pseudonymised (sha256 with a salt), message text is stored only up to
2000 chars; no names, usernames or Telegram IDs reach the RAG service at all.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time

import sqlalchemy as sa

from .. import db
from ..config import get_settings
from .questions import get_questions

log = logging.getLogger(__name__)


def pseudonymize(value: str) -> str:
    salt = os.environ.get("LOG_SALT", "bars-rag")
    return hashlib.sha256((salt + value).encode()).hexdigest()[:16]


def model_prices() -> dict[str, tuple[float, float]]:
    raw = get_settings().model_prices
    if not raw:
        return {}
    try:
        return {k: (float(v[0]), float(v[1])) for k, v in json.loads(raw).items()}
    except (ValueError, TypeError, IndexError, KeyError):
        log.warning("MODEL_PRICES is not valid JSON {model: [in, out]}")
        return {}


def cost_of(by_model: dict[str, dict]) -> tuple[float | None, str]:
    """USD cost of a turn from per-model token usage.

    A cost reported by the provider (OpenRouter `usage.cost`) wins; otherwise MODEL_PRICES is applied.
    Status: reported | known | partial | unknown (no price for any model of the turn)."""
    if not by_model:
        return 0.0, "known"
    reported = sum(u.get("cost", 0.0) or 0.0 for u in by_model.values())
    if reported > 0:
        return round(reported, 6), "reported"
    prices = model_prices()
    total, priced = 0.0, 0
    for m, u in by_model.items():
        if m in prices:
            pin, pout = prices[m]
            total += (u.get("prompt_tokens", 0) * pin + u.get("completion_tokens", 0) * pout) / 1_000_000
            priced += 1
    if not priced:
        return None, "unknown"
    return round(total, 6), "known" if priced == len(by_model) else "partial"


class QueryLogger:
    def log_turn(self, project_id: str, session_id: str, request_id: str, text: str, result: dict) -> None:
        trace = result.get("trace") or []
        internal = session_id.startswith("faq-build-")
        rec = {
            "ts": time.time(), "project_id": project_id, "session": pseudonymize(session_id), "request_id": request_id,
            "text": (text or "")[:2000], "answer": (result.get("text") or "")[:8000],
            "action": result.get("action"), "reason": result.get("reason"),
            "confidence": result.get("confidence"), "confidence_level": result.get("confidence_level"),
            "sources": [s.get("section_path") for s in result.get("sources", [])],
            "image_ids": result.get("image_ids"), "latency_ms": result.get("latency_ms"),
            "first_token_ms": result.get("first_token_ms"), "usage": result.get("usage"),
            "prompt_version": result.get("prompt_version"),
            "tool_calls": result.get("tool_calls"), "search_calls": result.get("search_calls"),
            # FR-AN-02/04, FR-FAQ-01/04: what the analytics and the FAQ clustering need
            "standalone": result.get("standalone"), "cache_hit": bool(result.get("cache_hit")),
            "cache_level": result.get("cache_level"), "faq_entry_id": result.get("faq_entry_id"),
            "has_images": bool(result.get("user_image_ids")),
            "tier": result.get("tier"), "route": result.get("route"), "models": result.get("models"),
            "search_queries": [(t.get("args") or {}).get("query") for t in trace
                               if t.get("step") == "tool" and t.get("tool") == "search_docs" and (t.get("args") or {}).get("query")],
            "internal": internal or None,
            "trace": trace,
        }
        try:
            # the record goes through JSON once so that everything in it is serialisable for any backend
            record = json.loads(json.dumps(rec, ensure_ascii=False, default=str))
            db.execute(sa.insert(db.turns).values(request_id=request_id, ts=rec["ts"], project_id=project_id, session=rec["session"],
                                                  action=rec["action"], internal=internal, record=record))
            get_questions().submit(record)  # classification + cluster in the background (analytics/questions.py)
        except Exception as e:  # noqa: BLE001  (analytics must never break the answer path)
            log.warning("turn log failed: %s", e)
