"""Panel endpoints for question classification and clusters (analytics/questions.py). Admin token, like /analytics/*.

GET  /analytics/clusters                 — clusters of the period with counts, answer rate, 👍/👎, examples
GET  /analytics/clusters/{cluster_id}    — one cluster with its questions
POST /analytics/clusters/rebuild         — rebuild clusters now (normally every QUESTION_CLUSTER_INTERVAL_S)
GET  /analytics/top-questions            — frequent questions (cluster representatives) + the FAQ entry serving them
GET  /analytics/unanswered               — documentation gaps: clusters / single questions without a good answer
GET  /analytics/topics                   — topic report: topics, intents, complexity, on/off-topic, doc sections
GET  /analytics/questions/{request_id}   — classification of one question
GET  /analytics/daily-digest             — classified questions of one calendar day (analytics/digest.py)
GET  /analytics/hot-answers              — level-1 answer cache by hits (hot answers) and FAQ entries by use
GET  /analytics/topics/tree              — hierarchy topic → clusters → examples (analytics/insights.py)
GET  /analytics/trends                   — daily series, rising / falling topics and clusters, spikes
GET  /analytics/clusters/map             — 2-D map (PCA) of questions and cluster centres for a scatter plot
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..analytics.questions import get_questions
from ..cache import get_cache
from ..core.config import get_settings
from ..index import store

router = APIRouter()


@router.get("/analytics/clusters")
def clusters(days: float = 30, limit: int = 50, project_id: str | None = None) -> dict:
    return get_questions().clusters(project_id, days, limit)


@router.get("/analytics/clusters/map")
def clusters_map(days: float = 30, limit: int = 600, project_id: str | None = None) -> dict:
    from ..analytics.insights import cluster_map

    return cluster_map(project_id, days, max(3, min(limit, 3000)))


@router.get("/analytics/trends")
def trends(days: int = 14, date: str | None = None, tz: str | None = None, project_id: str | None = None, limit: int = 30) -> dict:
    from ..analytics.insights import trends as build

    try:
        return build(project_id, max(2, min(days, 90)), tz, date, max(1, min(limit, 200)))
    except ValueError as e:
        raise HTTPException(422, f"date must be YYYY-MM-DD: {e}") from e
    except KeyError as e:
        raise HTTPException(422, f"unknown tz: {e}") from e


@router.get("/analytics/topics/tree")
def topics_tree(days: float = 30, project_id: str | None = None, clusters_per_topic: int = 20) -> dict:
    from ..analytics.insights import topic_tree

    return topic_tree(project_id, days, max(1, min(clusters_per_topic, 200)))


@router.get("/analytics/clusters/{cluster_id}")
def cluster(cluster_id: str, days: float = 30, project_id: str | None = None) -> dict:
    rep = get_questions().clusters(project_id, days, limit=1, cluster_id=cluster_id)
    if not rep["clusters"]:
        raise HTTPException(404, "cluster not found in the period")
    return rep["clusters"][0]


class RebuildIn(BaseModel):
    project_id: str | None = None
    days: int | None = None


@router.post("/analytics/clusters/rebuild")
async def rebuild(body: RebuildIn | None = None) -> dict:
    b = body or RebuildIn()
    return await asyncio.to_thread(get_questions().rebuild, b.project_id, b.days)


@router.get("/analytics/top-questions")
def top_questions(days: float = 30, limit: int = 20, project_id: str | None = None) -> dict:
    return get_questions().top_questions(project_id, days, limit)


@router.get("/analytics/daily-digest")
def daily_digest(date: str | None = None, project_id: str | None = None, tz: str | None = None, top: int = 10) -> dict:
    from ..analytics.digest import daily_digest as build

    try:
        return build(project_id, date, tz, top=max(1, min(top, 100)))
    except ValueError as e:  # bad date
        raise HTTPException(422, f"date must be YYYY-MM-DD: {e}") from e
    except KeyError as e:  # unknown time zone (ZoneInfoNotFoundError is a KeyError)
        raise HTTPException(422, f"unknown tz: {e}") from e


@router.get("/analytics/answer-clusters")
def answer_clusters(days: float = 30, top: int = 10, project_id: str | None = None) -> dict:
    """Questions grouped by question + answer + cited sections (ANSWER_CLUSTERS_ENABLED; otherwise {"enabled": false}):
    FAQ / cache candidates, documentation gaps, merge suggestions and answer consistency inside question clusters."""
    from ..analytics.answers import build

    return build(project_id, days, top=top)


@router.get("/analytics/unanswered")
def unanswered(days: float = 30, limit: int = 30, project_id: str | None = None) -> dict:
    return get_questions().unanswered(project_id, days, limit)


@router.get("/analytics/topics")
def topics(days: float = 30, project_id: str | None = None) -> dict:
    return get_questions().topics(project_id, days)


@router.get("/analytics/questions/{request_id}")
def question(request_id: str) -> dict:
    q = get_questions().question(request_id)
    if not q:
        raise HTTPException(404, "question not found")
    return q


@router.get("/analytics/hot-answers")
def hot_answers(limit: int = 20, project_id: str | None = None) -> dict:
    from ..faq import get_faq

    pid = project_id or get_settings().default_project_id
    gen = store.active_generation(pid)
    faq = sorted(get_faq().list_entries(pid), key=lambda e: -((e.get("served") or 0) + (e.get("likes") or 0) - (e.get("dislikes") or 0)))
    return {"project_id": pid, "generation": gen, "exact": get_cache().hot(pid, gen, limit) if gen else [],
            "faq": [{k: e.get(k) for k in ("id", "question", "served", "likes", "dislikes", "enabled", "origin")} for e in faq[:limit]]}
