"""Поиск фрагментов по активной версии индекса репозитория.

В PostgreSQL — оператор расстояния pgvector по индексу; в остальных СУБД (SQLite в тестах)
косинусная близость считается в Python.
"""

import math
from dataclasses import dataclass

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EMBEDDING_DIM, Chunk, Repository


@dataclass
class Hit:
    chunk: Chunk
    score: float  # косинусная близость, чем больше, тем ближе


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


async def search_many(
    session: AsyncSession,
    repo: Repository,
    vectors: list[list[float]],
    *,
    k: int,
    min_score: float,
) -> list[Hit]:
    """Объединяет результаты по нескольким запросам: у каждого фрагмента лучшая оценка."""
    best: dict[int, Hit] = {}
    for vector in vectors:
        for hit in await search(session, repo, vector, k=k, min_score=min_score):
            if hit.chunk.id not in best or hit.score > best[hit.chunk.id].score:
                best[hit.chunk.id] = hit
    return sorted(best.values(), key=lambda h: h.score, reverse=True)[:k]


async def search(
    session: AsyncSession, repo: Repository, vector: list[float], *, k: int, min_score: float
) -> list[Hit]:
    """Ближайшие фрагменты активной версии, не ниже порога сходства."""
    if repo.active_index_id is None:
        return []
    version = Chunk.index_version_id == repo.active_index_id

    if session.bind.dialect.name == "postgresql":
        query = literal(vector, type_=Vector(EMBEDDING_DIM))
        distance = Chunk.embedding.op("<=>", return_type=Float)(query)  # косинусное расстояние
        rows = (
            await session.execute(
                select(Chunk, distance.label("distance")).where(version).order_by(distance).limit(k)
            )
        ).all()
        hits = [Hit(chunk, 1.0 - float(dist)) for chunk, dist in rows]
    else:
        rows = (await session.execute(select(Chunk.id, Chunk.embedding).where(version))).all()
        scored = sorted(((_cosine(vector, emb), cid) for cid, emb in rows), reverse=True)[:k]
        by_id = {
            c.id: c
            for c in await session.scalars(select(Chunk).where(Chunk.id.in_([i for _, i in scored])))
        }
        hits = [Hit(by_id[cid], score) for score, cid in scored]
    return [h for h in hits if h.score >= min_score]
