"""Relational storage (FR-AN-01, FR-AGT-05): turns with traces, feedback, classification, jobs, operator answers.

SQLAlchemy Core (MIT). DATABASE_URL points to Postgres in docker-compose (pg8000 driver, BSD);
without it a sqlite file in STATE_DIR is used, so dev and unit tests need no server.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import sqlalchemy as sa

from .config import get_settings

log = logging.getLogger(__name__)
meta = sa.MetaData()

# One row per turn. `record` is the full query-log entry (question, action, sources, usage, trace, routing…);
# the plain columns exist only to select and filter without reading the JSON.
turns = sa.Table(
    "rag_turns", meta,
    sa.Column("request_id", sa.String(32), primary_key=True),
    sa.Column("ts", sa.Float, index=True),
    sa.Column("project_id", sa.String(64), index=True),
    sa.Column("session", sa.String(32), index=True),  # pseudonymised session id (NFR-05)
    sa.Column("action", sa.String(24), index=True),
    sa.Column("internal", sa.Boolean, default=False),  # turns of the FAQ answer builder, excluded from statistics
    sa.Column("record", sa.JSON),
)

feedback = sa.Table(
    "rag_feedback", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("ts", sa.Float, index=True),
    sa.Column("request_id", sa.String(32), index=True),
    sa.Column("kind", sa.String(24)),  # rating | escalation_unneeded
    sa.Column("rating", sa.String(8)),  # up | down (kind=rating)
    sa.Column("session", sa.String(32)),
    sa.Column("comment", sa.Text),
)

# FR-AN-04: result of the asynchronous classification of a turn
classes = sa.Table(
    "rag_classes", meta,
    sa.Column("request_id", sa.String(32), primary_key=True),
    sa.Column("data", sa.JSON),
)

# small admin-editable documents (the topic taxonomy)
kv = sa.Table(
    "rag_kv", meta,
    sa.Column("key", sa.String(64), primary_key=True),
    sa.Column("value", sa.JSON),
)

jobs = sa.Table(
    "rag_jobs", meta,
    sa.Column("job_id", sa.String(16), primary_key=True),
    sa.Column("kind", sa.String(32)),
    sa.Column("status", sa.String(16), index=True),  # queued | running | done | failed | interrupted
    sa.Column("project_id", sa.String(64)),
    sa.Column("params", sa.JSON),  # set for jobs that can be repeated after a restart (indexing a folder)
    sa.Column("report", sa.JSON),
    sa.Column("error", sa.Text),
    sa.Column("note", sa.Text),
    sa.Column("created_at", sa.Float),
    sa.Column("started_at", sa.Float),
    sa.Column("finished_at", sa.Float),
)

knowledge = sa.Table(
    "rag_knowledge", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("ts", sa.Float),
    sa.Column("project_id", sa.String(64)),
    sa.Column("question", sa.Text),
    sa.Column("answer", sa.Text),
    sa.Column("author", sa.String(128)),
    sa.Column("file", sa.String(255)),
    sa.Column("job_id", sa.String(16)),
)

# analytics/questions.py: classification of every question and its topic cluster (assigned online, rebuilt in background)
questions = sa.Table(
    "rag_questions", meta,
    sa.Column("request_id", sa.String(32), primary_key=True),
    sa.Column("ts", sa.Float, index=True),
    sa.Column("project_id", sa.String(64), index=True),
    sa.Column("session", sa.String(32)),  # pseudonymised (NFR-05)
    sa.Column("user_ref", sa.String(64), index=True),  # optional salted hash from the bot (QUESTION_USER_REF_ENABLED)
    sa.Column("text", sa.Text),  # standalone form of the question (follow-up → the agent's search query)
    sa.Column("intent", sa.String(16), index=True),  # question | error | operator | smalltalk
    sa.Column("topic", sa.String(128), index=True),
    sa.Column("doc_section", sa.String(255)),
    sa.Column("complexity", sa.String(8)),  # simple | complex (model routing) | null for cache answers
    sa.Column("on_topic", sa.Boolean),
    sa.Column("outcome", sa.String(24)),
    sa.Column("answered", sa.Boolean),
    sa.Column("cluster_id", sa.String(16), index=True),
    sa.Column("similarity", sa.Float),
    sa.Column("data", sa.JSON),
)

question_clusters = sa.Table(
    "rag_question_clusters", meta,
    sa.Column("cluster_id", sa.String(16), primary_key=True),
    sa.Column("project_id", sa.String(64), index=True),
    sa.Column("label", sa.String(255)),
    sa.Column("label_by", sa.String(8)),  # llm | medoid
    sa.Column("medoid", sa.Text),
    sa.Column("centroid", sa.JSON),
    sa.Column("size", sa.Integer),
    sa.Column("topic", sa.String(128)),
    sa.Column("active", sa.Boolean, index=True),
    sa.Column("created_at", sa.Float),
    sa.Column("updated_at", sa.Float),
    sa.Column("data", sa.JSON),
)

_engine: sa.Engine | None = None
_lock = threading.Lock()


def engine() -> sa.Engine:
    global _engine
    with _lock:
        if _engine is None:
            s = get_settings()
            url = s.database_url
            if not url:
                Path(s.state_dir).mkdir(parents=True, exist_ok=True)
                url = f"sqlite:///{(Path(s.state_dir) / 'rag.sqlite').as_posix()}"
            kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
            _engine = sa.create_engine(url, future=True, **kw)
            meta.create_all(_engine)
            log.info("relational storage: %s", _engine.url.render_as_string(hide_password=True))
        return _engine


def reset_engine() -> None:
    """Drop the cached engine (tests switch STATE_DIR / DATABASE_URL)."""
    global _engine
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None


def execute(stmt) -> sa.CursorResult:
    with engine().begin() as c:
        return c.execute(stmt)


def rows(stmt) -> list[dict]:
    with engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(stmt)]


def one(stmt) -> dict | None:
    r = rows(stmt)
    return r[0] if r else None


def upsert(table: sa.Table, key: str, key_value, values: dict) -> None:
    """Portable insert-or-update by primary key (works the same on Postgres and sqlite)."""
    with engine().begin() as c:
        done = c.execute(sa.update(table).where(table.c[key] == key_value).values(**values))
        if not done.rowcount:
            c.execute(sa.insert(table).values(**{key: key_value}, **values))


def ping() -> bool:
    try:
        with engine().connect() as c:
            c.execute(sa.text("select 1"))
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("database unavailable: %s", e)
        return False
