"""Embedder (Miro S110, FR-RET-05): OpenAI-compatible endpoint, OpenRouter, or local fastembed (multilingual-e5).

EMBEDDING_PROVIDER=openrouter: the same OpenAI-compatible call through OpenRouter (OPENROUTER_API_KEY /
OPENROUTER_BASE_URL unless EMBEDDING_API_KEY / EMBEDDING_BASE_URL are set), e.g. EMBEDDING_MODEL=google/gemini-embedding-001 —
the vectors equal Gemini direct (cosine 1.0, scripts/compare_embeddings.py), so the Qdrant index and the disk cache stay
valid; no free-tier daily quota.

Embeddings are cached on disk (sqlite, keyed by model + sha1(text)) so re-indexing and repeated
queries do not spend quota; a client-side items/minute limiter keeps under provider limits.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import struct
import threading
import time
from collections import deque
from functools import lru_cache
from pathlib import Path

from openai import OpenAI

from ..core.config import get_settings

log = logging.getLogger(__name__)


class _DiskCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("create table if not exists emb (k text primary key, v blob)")
        self._lock = threading.Lock()

    def get(self, k: str) -> list[float] | None:
        with self._lock:
            row = self._db.execute("select v from emb where k=?", (k,)).fetchone()
        if not row:
            return None
        b = row[0]
        return list(struct.unpack(f"{len(b) // 4}f", b))

    def put(self, k: str, v: list[float]) -> None:
        with self._lock:
            self._db.execute("insert or replace into emb values (?,?)", (k, struct.pack(f"{len(v)}f", *v)))
            self._db.commit()


class Embedder:
    def __init__(self) -> None:
        s = get_settings()
        self.provider = s.embedding_provider
        self.model = s.embedding_model
        self.dim_req = s.embedding_dim
        self.items_per_min = s.embedding_items_per_min
        self._win: deque = deque()
        self._wl = threading.Lock()
        self.cache = _DiskCache(Path(s.state_dir) / "embedding_cache.sqlite")
        if self.provider == "fastembed":
            from fastembed import TextEmbedding  # Apache-2.0, ONNX runtime (MIT)

            self._fe = TextEmbedding(model_name=self.model)
        elif self.provider == "openrouter":
            self._client = OpenAI(
                api_key=s.embedding_api_key or s.openrouter_api_key or None,
                base_url=s.embedding_base_url or s.openrouter_base_url,
                timeout=60, max_retries=0,
            )
        else:
            self._client = OpenAI(
                api_key=s.embedding_api_key or s.llm_api_key or None,
                base_url=s.embedding_base_url or s.llm_base_url or None,
                timeout=60, max_retries=0,
            )

    @property
    def is_e5(self) -> bool:
        return "e5" in self.model.lower()

    def _key(self, text: str) -> str:
        # «google/gemini-embedding-001» on OpenRouter returns the same vectors as Gemini direct (cos = 1.0) → shared cache
        provider = "openai" if self.provider == "openrouter" else self.provider  # same API and vectors → same cache entries
        return f"{provider}:{self.model.rsplit('/', 1)[-1]}:{self.dim_req}:" + hashlib.sha1(text.encode("utf-8")).hexdigest()

    def _throttle(self, n: int) -> None:
        if not self.items_per_min:
            return
        while True:
            with self._wl:
                now = time.time()
                while self._win and now - self._win[0][0] > 60:
                    self._win.popleft()
                used = sum(c for _, c in self._win)
                if used + n <= self.items_per_min or not self._win:
                    self._win.append((now, n))
                    return
                wait = 60 - (now - self._win[0][0]) + 0.2
            time.sleep(max(0.2, wait))

    def _embed_remote(self, texts: list[str], timeout: float | None = None, attempts: int = 6) -> list[list[float]]:
        if self.provider == "fastembed":
            return [list(map(float, v)) for v in self._fe.embed(texts, batch_size=16)]
        out: list[list[float]] = []
        step = 32
        for i in range(0, len(texts), step):
            batch = texts[i:i + step]
            kw = {"dimensions": self.dim_req} if self.dim_req else {}
            cl = self._client.with_options(timeout=timeout) if timeout else self._client
            for attempt in range(attempts):
                try:
                    self._throttle(len(batch))
                    r = cl.embeddings.create(model=self.model, input=batch, **kw)
                    break
                except Exception as e:  # noqa: BLE001
                    pause = _retry_pause(e, attempt)
                    if pause is None or attempt == attempts - 1:
                        raise
                    if timeout:
                        pause = min(pause, 1.0)  # a query on the answer path: short pauses
                    log.warning("embedding retry in %.1fs (attempt %s): %s", pause, attempt + 1, str(e)[:120])
                    time.sleep(pause)
            out.extend(d.embedding for d in r.data)
        return out

    def _embed(self, texts: list[str], timeout: float | None = None, attempts: int = 6) -> list[list[float]]:
        res: list[list[float] | None] = [self.cache.get(self._key(t)) for t in texts]
        missing = [i for i, v in enumerate(res) if v is None]
        if missing:
            vecs = self._embed_remote([texts[i] for i in missing], timeout=timeout, attempts=attempts)
            for i, v in zip(missing, vecs):
                res[i] = v
                self.cache.put(self._key(texts[i]), v)
        return res  # type: ignore[return-value]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.is_e5:
            texts = [f"passage: {t}" for t in texts]
        return self._embed(texts)

    def embed_query(self, text: str, timeout: float | None = None) -> list[float]:
        """`timeout` (RETRIEVAL_DENSE_TIMEOUT_S): a query on the answer path gets 2 short attempts instead of 6 × 60 s."""
        if self.is_e5:
            text = f"query: {text}"
        if timeout and self.provider != "fastembed":
            return self._embed([text], timeout=timeout, attempts=2)[0]
        return self._embed([text])[0]


def _retry_pause(e: Exception, attempt: int) -> float | None:
    """NFR-04: 429 / 5xx / network → exponential backoff with jitter (honours Retry-After); 4xx → no retry."""
    import random

    status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    if status is not None and status != 429 and status < 500 and status not in (408, 409):
        return None  # bad request / auth / dimension mismatch: retrying will not help
    retry_after = None
    try:
        retry_after = float(e.response.headers.get("retry-after"))  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError):
        pass
    base = (4.0 if status == 429 else 1.0) * (2 ** attempt)
    return min(60.0, max(retry_after or 0.0, base)) * random.uniform(0.8, 1.2)


@lru_cache
def get_embedder() -> Embedder:
    return Embedder()
