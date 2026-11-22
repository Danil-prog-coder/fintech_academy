"""Project statistics for the site: the platform's own journal plus the RAG's analytics when it is reachable.

Aggregation is done over the period's rows in Python: a project asks a few thousand questions a month, well within
what one query returns. Past ~10^5 turns per period this should move to SQL GROUP BY (or a daily roll-up table).
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.runtime import Core
from ..db.models import Escalation, EscalationStatus, Member, Project, Question, QuestionStatus, Turn
from ..db.session import utc_now
from .rag import RagError, RagUnavailable


def _days(since, days: int) -> list[str]:
    """Every day of the period (a chart with gaps on quiet days would mislead)."""
    start = since.date()
    return [(start + timedelta(days=i + 1)).isoformat() for i in range(days)]


async def summary(core: Core, session: AsyncSession, project: Project, days: int) -> dict:
    since = utc_now() - timedelta(days=days)
    turns = (await session.scalars(select(Turn).where(Turn.project_id == project.id, Turn.created_at >= since)
                                   .order_by(Turn.id).limit(100_000))).all()
    actions = Counter(t.action for t in turns)
    per_day: dict[str, Counter] = {}
    for t in turns:
        per_day.setdefault(t.created_at.date().isoformat(), Counter())[t.action] += 1
    ratings = Counter(t.rating for t in turns if t.rating)
    latencies = sorted(t.latency_ms for t in turns if t.latency_ms)
    esc_rows = (await session.execute(select(Escalation.status, func.count()).where(Escalation.project_id == project.id)
                                      .group_by(Escalation.status))).all()
    esc = {s: n for s, n in esc_rows}
    pending_q = await session.scalar(select(func.count()).select_from(Question).where(
        Question.project_id == project.id, Question.status == QuestionStatus.PENDING))
    members = dict((await session.execute(select(Member.role, func.count()).where(Member.project_id == project.id)
                                          .group_by(Member.role))).all())
    total = len(turns)
    out = {
        "period_days": days,
        "questions": total,
        "answered": actions.get("answer", 0),
        "answered_share": round(actions.get("answer", 0) / total, 3) if total else None,
        "actions": dict(actions),
        "cache_hits": sum(1 for t in turns if t.cache_hit),
        "unique_users": len({t.external_id for t in turns}),
        "latency_ms_p50": latencies[len(latencies) // 2] if latencies else None,
        "latency_ms_p90": latencies[int(len(latencies) * 0.9)] if latencies else None,
        "ratings": {"up": ratings.get(1, 0), "down": ratings.get(-1, 0)},
        "unanswered_pending": int(pending_q or 0),
        "escalations": {"open": sum(n for s, n in esc.items() if EscalationStatus(s).is_open),
                        "closed": sum(n for s, n in esc.items() if not EscalationStatus(s).is_open), "by_status": esc},
        "members": members,
        "by_day": [{"date": d, "total": sum(per_day.get(d, Counter()).values()), **dict(per_day.get(d, Counter()))}
                   for d in _days(since, days)],
        "top_unanswered": [q for q, _ in Counter(t.question.strip().lower() for t in turns
                                                 if t.action == "offer_operator").most_common(10)],
    }
    try:
        rag = await core.rag.analytics_summary(project.rag_project_id, days)
        out["rag"] = {k: rag.get(k) for k in ("topics", "cost_usd", "tokens", "routing", "cache", "feedback", "latency")
                      if k in rag}
    except (RagError, RagUnavailable):
        out["rag"] = None
    return out
