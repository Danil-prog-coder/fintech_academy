"""Answer caches (Miro S75 ExactCache, S81 SemanticFaqCache; NFR-01, FR-FAQ-04).

Level 1 — the exact cache: normalised question text → verified answer, stored in Redis
(in-process dict without Redis). The key contains project_id and the active generation, so publishing a
new version of the knowledge base invalidates the cache automatically (FR-ARCH-04).
Only self-contained questions (first in the session, no images/links/deal numbers/filter expressions,
no operator request) are looked up and stored, and only `answer` results with high confidence are stored.
Hot answers: every hit is counted once per person (user_ref or pseudonymised session) in a per-generation sorted
set; a hit extends the entry's TTL (ANSWER_CACHE_SLIDING_TTL), and above ANSWER_CACHE_MAX_ENTRIES the entries with
the fewest people are evicted first — frequently used answers stay, cold ones go. `hot()` lists them for the panel.
Level 2 — the semantic top-K FAQ cache (FR-FAQ-01..08) lives in `rag_service.faq`; `SemanticFaqCache` below is
its thin adapter with the same interface.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from typing import Protocol

from ..config import get_settings

log = logging.getLogger(__name__)


class AnswerCache(Protocol):
    def lookup(self, project_id: str, generation: str, question: str) -> dict | None: ...

    def store(self, project_id: str, generation: str, question: str, result: dict) -> None: ...


def normalize_question(q: str) -> str:
    t = (q or "").lower().replace("ё", "е")
    t = re.sub(r"[«»“”„\"'`?!.,;:()]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_STORED_FIELDS = ("action", "text", "sources", "image_ids", "confidence", "confidence_level", "reason", "buttons",
                  "prompt_version")


class ExactCache:
    def __init__(self) -> None:
        from ..agent.memory import get_memory

        self.ttl = get_settings().answer_cache_ttl_s
        self._redis = get_memory()._redis
        self._mem: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self._hits: dict[str, dict[str, int]] = {}  # in-process backend of the hot-answer counters
        self._who: dict[str, set[str]] = {}

    @staticmethod
    def key(project_id: str, generation: str, question: str) -> str:
        h = hashlib.sha1(normalize_question(question).encode()).hexdigest()[:20]
        return f"rag:{project_id}:{generation}:answer:{h}"

    def lookup(self, project_id: str, generation: str, question: str, who: str | None = None) -> dict | None:
        k = self.key(project_id, generation, question)
        raw = None
        if self._redis is not None:
            try:
                raw = self._redis.get(k)
            except Exception as e:  # noqa: BLE001
                log.warning("cache get failed: %s", e)
        else:
            with self._lock:
                item = self._mem.get(k)
                raw = item[1] if item and item[0] > time.time() else None
        if raw:
            from ..retrieval.access import answer_allowed

            if not answer_allowed(project_id, json.loads(raw)):
                return None
            self._touch(project_id, generation, k, raw, who)
        return json.loads(raw) if raw else None

    # ---- hot answers: people per entry, sliding TTL, bounded size
    @staticmethod
    def _hits_key(project_id: str, generation: str) -> str:
        return f"rag:{project_id}:{generation}:answer:_hits"

    def _touch(self, project_id: str, generation: str, k: str, raw: str, who: str | None) -> None:
        s = get_settings()
        hk = self._hits_key(project_id, generation)
        try:
            if self._redis is not None:
                new = self._redis.sadd(k + ":who", who) if who else 1
                if new:
                    self._redis.zincrby(hk, 1, k)
                if who:
                    self._redis.expire(k + ":who", self.ttl)
                if s.answer_cache_sliding_ttl:
                    self._redis.expire(k, self.ttl)
                return
        except Exception as e:  # noqa: BLE001
            log.warning("cache hit count failed: %s", e)
        with self._lock:
            people = self._who.setdefault(k, set())
            if not who or who not in people:
                if who:
                    people.add(who)
                self._hits.setdefault(hk, {})[k] = self._hits.get(hk, {}).get(k, 0) + 1
            if s.answer_cache_sliding_ttl and k in self._mem:
                self._mem[k] = (time.time() + self.ttl, raw)

    def _bound(self, project_id: str, generation: str, k: str) -> None:
        cap = get_settings().answer_cache_max_entries
        hk = self._hits_key(project_id, generation)
        try:
            if self._redis is not None:
                self._redis.zadd(hk, {k: 0}, nx=True)
                self._redis.expire(hk, self.ttl * 7)
                extra = (self._redis.zcard(hk) or 0) - cap
                if cap and extra > 0:
                    colds = [c.decode() if isinstance(c, bytes) else c for c in self._redis.zrange(hk, 0, extra)]
                    for cold in [c for c in colds if c != k][:extra]:  # the entry just stored is never the victim
                        self._redis.delete(cold, cold + ":who")
                        self._redis.zrem(hk, cold)
                return
        except Exception as e:  # noqa: BLE001
            log.warning("cache bound failed: %s", e)
        with self._lock:
            hits = self._hits.setdefault(hk, {})
            hits.setdefault(k, 0)
            if cap and len(hits) > cap:
                for cold, _ in sorted(((a, b) for a, b in hits.items() if a != k), key=lambda x: x[1])[:len(hits) - cap]:
                    hits.pop(cold, None)
                    self._mem.pop(cold, None)
                    self._who.pop(cold, None)

    def hot(self, project_id: str, generation: str, limit: int = 20) -> list[dict]:
        """Panel: cached answers of the generation by the number of people they served."""
        hk = self._hits_key(project_id, generation)
        pairs: list[tuple[str, float]] = []
        if self._redis is not None:
            try:
                pairs = [(a.decode() if isinstance(a, bytes) else a, b) for a, b in self._redis.zrevrange(hk, 0, limit - 1, withscores=True)]
            except Exception as e:  # noqa: BLE001
                log.warning("cache hot failed: %s", e)
        else:
            with self._lock:
                pairs = sorted(self._hits.get(hk, {}).items(), key=lambda x: -x[1])[:limit]
        out = []
        for k, n in pairs:
            raw = None
            if self._redis is not None:
                try:
                    raw = self._redis.get(k)
                except Exception:  # noqa: BLE001
                    raw = None
            else:
                item = self._mem.get(k)
                raw = item[1] if item and item[0] > time.time() else None
            if raw:
                d = json.loads(raw)
                out.append({"question": d.get("question"), "people": int(n), "cached_at": d.get("cached_at")})
        return out

    def store(self, project_id: str, generation: str, question: str, result: dict) -> None:
        if result.get("action") != "answer" or result.get("confidence_level") != "high" or not result.get("sources"):
            return
        k = self.key(project_id, generation, question)
        raw = json.dumps({f: result.get(f) for f in _STORED_FIELDS} | {"cached_at": time.time(), "question": question},
                         ensure_ascii=False)
        if self._redis is not None:
            try:
                self._redis.set(k, raw, ex=self.ttl)
                self._bound(project_id, generation, k)
                return
            except Exception as e:  # noqa: BLE001
                log.warning("cache set failed: %s", e)
        with self._lock:
            self._mem[k] = (time.time() + self.ttl, raw)
        self._bound(project_id, generation, k)

    def clear(self, project_id: str) -> int:
        n = 0
        if self._redis is not None:
            try:
                for k in self._redis.scan_iter(f"rag:{project_id}:*:answer:*"):
                    self._redis.delete(k)
                    n += 1
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            for k in [k for k in self._mem if k.startswith(f"rag:{project_id}:")]:
                self._mem.pop(k)
                n += 1
            for hk in [hk for hk in self._hits if hk.startswith(f"rag:{project_id}:")]:
                self._hits.pop(hk)
            for k in [k for k in self._who if k.startswith(f"rag:{project_id}:")]:
                self._who.pop(k)
        return n


class SemanticFaqCache:
    """Top-K FAQ cache with entity check and equivalence verification (FR-FAQ-04) — adapter to rag_service.faq.

    `store` is a no-op on purpose: FAQ answers are built by the recompute job for top-K clusters (FR-FAQ-03),
    not from arbitrary user turns.
    """

    def lookup(self, project_id: str, generation: str, question: str) -> dict | None:
        from ..faq import get_faq

        return get_faq().lookup(project_id, generation, question)

    def store(self, project_id: str, generation: str, question: str, result: dict) -> None:
        return None


def is_cacheable_question(message: str, has_images: bool, is_first_in_session: bool) -> bool:
    """Miro D2.02: self-contained question without images, links, deal numbers or filter expressions."""
    from ..agent.guardrails import is_operator_request

    if has_images or not is_first_in_session or is_operator_request(message):
        return False
    from ..tools.bo_link import hosts

    if any(h in (message or "").lower() for h in hosts()):
        return False
    return not re.search(r"(https?://|\d{3,}-\d{2}|!>|>=|<=|!=|<>|\bin\s)", message or "", re.I)


# anaphora: a question that leans on the previous turn («как оформить её заранее?») is not self-contained
_ANAPHORA = frozenset("""он она оно они его ее их ему ей им ими него нее ней нему ним ними них
это этот эта эти этого этой этому этим этом эту этих этими тот того тому том те тех теми
такой такая такое такие такого таком там туда оттуда тогда""".split())


def is_self_contained(message: str) -> bool:
    """A message in the middle of a session that does not lean on the dialog: >= 4 words, not a follow-up
    («а в выходные?», guard._FOLLOWUP), no anaphoric pronouns. Such a question may use the answer cache too."""
    from ..guard import _FOLLOWUP

    words = re.findall(r"\w+", (message or "").lower().replace("ё", "е"))
    return len(words) >= 4 and not _FOLLOWUP.search(message or "") and not _ANAPHORA.intersection(words)


_cache: ExactCache | None = None


def get_cache() -> ExactCache:
    global _cache
    if _cache is None:
        _cache = ExactCache()
    return _cache
