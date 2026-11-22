"""LLM reranker (FR-RET-04): candidate_k -> scores 0..10 in one cheap call; falls back to RRF order.

The call has its own time budget (RERANK_TIMEOUT_S). A slow or stalled provider must not hold the whole turn:
on 14–15.11 single searches took 23–44 s while the reranker waited for retries and fallback models. Past the
budget the search keeps the fused (RRF) order — on the retrieval bench that order loses 1 case of 29 at Hit@5
(scripts/retrieval_bench.py), a far smaller loss than a turn that runs out of time.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from ..config import get_settings
from ..llm import LLMUnavailable, chat

log = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="rerank")  # a queued call eats into the budget too

PROMPT = """Ты — реранкер поиска по корпоративной документации. Оцени, насколько каждый фрагмент помогает ответить на запрос.
10 — фрагмент прямо содержит ответ; 7 — содержит важную часть ответа; 4 — по теме, но ответа нет; 0 — не относится.
Учитывай точные объекты: если запрос называет один документ, реестр или экран, а фрагмент описывает другой, пусть и похожий по названию, это НЕ прямой ответ (не выше 5).
Ответ строго JSON: {"scores": [{"i": <номер>, "s": <0-10>}, ...]} для всех фрагментов."""


def llm_rerank(query: str, candidates: list[dict]) -> list[float] | None:
    """Scores 0..1 in candidate order; None — keep the fused order (error, bad JSON or the time budget is over)."""
    s = get_settings()
    if not candidates:
        return []
    lines = []
    for i, c in enumerate(candidates):
        body = re.sub(r"\s+", " ", c["text"])[:650]
        lines.append(f"[{i}] ({c['chunk_type']}) {c['section_path_str']}\n{body}")
    user = f"Запрос: {query}\n\nФрагменты:\n" + "\n\n".join(lines)

    def call(model: str | None = None):
        return chat(
            model=model or s.rerank_model,
            messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0,
            retries=1,
        )

    try:
        chain = [m.strip() for m in s.rerank_model.split(",") if m.strip()]
        if s.rerank_hedge_after_s > 0 and len(chain) > 1:
            r = _hedged(call, chain, s.rerank_hedge_after_s, s.rerank_timeout_s)
            if r is None:
                return None
        elif s.rerank_timeout_s and s.rerank_timeout_s > 0:
            # the caller's context goes along, so the reranker's tokens still land in the turn's usage meter;
            # a call past the budget finishes in its thread, and its result is dropped
            future = _pool.submit(contextvars.copy_context().run, call)
            try:
                r = future.result(timeout=s.rerank_timeout_s)
            except FutureTimeout:
                log.warning("rerank exceeded %.1f s, using fused order", s.rerank_timeout_s)
                return None
        else:
            r = call()
        raw = r.choices[0].message.content or "{}"
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        scores = [0.0] * len(candidates)
        for item in data.get("scores", []):
            i = int(item.get("i", -1))
            if 0 <= i < len(candidates):
                scores[i] = max(0.0, min(10.0, float(item.get("s", 0)))) / 10.0
        return scores
    except (LLMUnavailable, ValueError, AttributeError, json.JSONDecodeError) as e:
        log.warning("rerank failed, using fused order: %s", str(e)[:200])
        return None



def _hedged(call, chain: list[str], after: float, budget: float):
    from ..llm import hedged_call

    return hedged_call(call, chain, after, budget, pool=_pool, what="rerank")
