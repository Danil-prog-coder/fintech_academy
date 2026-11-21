"""SessionMemory (FR-AGT-05, Miro S90): dialog history + source registry in Redis with TTL.

Falls back to an in-process TTL dict when REDIS_URL is not set/unreachable (dev, tests).
Key: f"rag:{project_id}:session:{session_id}" — project_id is part of every key (FR-ARCH-01).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from ..config import get_settings

log = logging.getLogger(__name__)


def new_session(session_id: str, project_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id, "project_id": project_id, "created_at": time.time(),
        "messages": [],  # [{role, content, action?, sources?}]
        "summary": "",
        "registry": {},  # source_id -> compact source (S1.., T1..)
        "next_s": 1, "next_t": 1,
        "tokens_used": 0, "turns": 0, "clarify_streak": 0, "failed_streak": 0,
    }


class SessionMemory:
    def __init__(self) -> None:
        s = get_settings()
        self.ttl = s.session_ttl_s
        self._redis = None
        self._mem: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        if s.redis_url:
            try:
                import redis

                self._redis = redis.Redis.from_url(s.redis_url, socket_timeout=2)
                self._redis.ping()
            except Exception as e:  # noqa: BLE001
                log.warning("Redis unavailable (%s) — using in-process session store", e)
                self._redis = None

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "memory"

    @staticmethod
    def key(project_id: str, session_id: str) -> str:
        return f"rag:{project_id}:session:{session_id}"

    def load(self, session_id: str, project_id: str) -> dict:
        k = self.key(project_id, session_id)
        raw = None
        if self._redis is not None:
            try:
                raw = self._redis.get(k)
            except Exception as e:  # noqa: BLE001
                log.warning("redis get failed: %s", e)
        else:
            with self._lock:
                item = self._mem.get(k)
                if item and item[0] > time.time():
                    raw = item[1]
        sess = json.loads(raw) if raw else new_session(session_id, project_id)
        from ..retrieval.access import revision

        current = revision(project_id)
        if sess.get("access_revision", "") != current:
            # Old assistant text/summary/registry may contain withdrawn source content.
            # Clear model context, keeping the conversation itself in the external audit log.
            sess = new_session(session_id, project_id)
        sess["access_revision"] = current
        return sess

    def save(self, sess: dict) -> None:
        k = self.key(sess["project_id"], sess["session_id"])
        raw = json.dumps(sess, ensure_ascii=False)
        if self._redis is not None:
            try:
                self._redis.set(k, raw, ex=self.ttl)
                return
            except Exception as e:  # noqa: BLE001
                log.warning("redis set failed: %s", e)
        with self._lock:
            self._mem[k] = (time.time() + self.ttl, raw)

    def reset(self, session_id: str, project_id: str) -> None:
        k = self.key(project_id, session_id)
        if self._redis is not None:
            try:
                self._redis.delete(k)
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._mem.pop(k, None)

    def ping(self) -> bool:
        if self._redis is None:
            return True
        try:
            return bool(self._redis.ping())
        except Exception:  # noqa: BLE001
            return False


_memory: SessionMemory | None = None


def get_memory() -> SessionMemory:
    global _memory
    if _memory is None:
        _memory = SessionMemory()
    return _memory
