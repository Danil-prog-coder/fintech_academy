"""Embedder of the question analytics (classification refine, clusters, map), with per-model thresholds and a local
fallback.

* The main embedder is the retrieval one (``FaqService.embed``: same vectors and disk cache as search).
* When it fails (429 / quota / network), analytics switches to a local ONNX model (``QUESTION_FALLBACK_EMBEDDER``,
  default BAAI/bge-m3 via fastembed, MIT) for ``QUESTION_FALLBACK_COOLDOWN_S``. Retrieval in Qdrant is never touched:
  the fallback vectors live only in the analytics (clusters remember the model they were built with).
* Cosine thresholds depend on the embedder (e5 / bge-m3 / gemini have different similarity scales; with the gemini
  thresholds bge-m3 gives ARI 0.55, e5 — 0.0, eval/clustering/methods.md). The main model uses the QUESTION_*
  settings; any other model takes its row of THRESHOLDS, calibrated on the golden-set log; a model without a row
  falls back to the settings with a warning.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import numpy as np

from ..core.config import get_settings

log = logging.getLogger(__name__)

# calibrated on the golden-set log (eval/clustering/compare_methods.py, nested_cv.py, report.md)
THRESHOLDS: dict[str, dict[str, float]] = {
    "gemini-embedding-001": {"assign": 0.82, "cluster": 0.82, "merge": 0.86},  # ARI 0.897, nested 0.88
    "bge-m3": {"assign": 0.76, "cluster": 0.74, "merge": 0.80},  # ARI 0.903, online P 0.88 / R 0.93
    "multilingual-e5-large": {"assign": 0.90, "cluster": 0.90, "merge": 0.94},  # ARI 0.874 (assign not calibrated)
}
_warned: set[str] = set()


def model_key(name: str | None) -> str:
    """«google/gemini-embedding-001», «models/gemini-embedding-001» → «gemini-embedding-001»; «BAAI/bge-m3» → «bge-m3»."""
    return (name or "").rsplit("/", 1)[-1].lower()


def main_model() -> str:
    return model_key(get_settings().embedding_model)


def thresholds(model: str | None = None) -> dict[str, float]:
    """{"assign", "cluster", "merge"} for vectors of `model` (default: the main embedder)."""
    s = get_settings()
    key = model_key(model) if model else main_model()
    own = {"assign": s.question_assign_threshold, "cluster": s.question_cluster_threshold, "merge": s.question_merge_threshold,
           "pair": s.question_pair_threshold}
    if key == main_model():
        if key not in THRESHOLDS and key not in _warned:
            _warned.add(key)
            log.warning("question clusters: thresholds are calibrated for %s, EMBEDDING_MODEL=%s is not — set QUESTION_*_THRESHOLD "
                        "(eval/clustering/compare_methods.py) or results will be poor", ", ".join(THRESHOLDS), key)
        return own
    if key in THRESHOLDS:
        return THRESHOLDS[key]
    if key not in _warned:
        _warned.add(key)
        log.warning("question clusters: no calibrated thresholds for embedder %s, using the QUESTION_* settings", key)
    return own


class _Local:
    """Lazy fastembed model (ONNX on CPU); bge-m3 is registered as a custom model (CLS pooling, normalised)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._m = None
        self.name: str | None = None

    def get(self):
        s = get_settings()
        with self._lock:
            if self._m is None or self.name != s.question_fallback_embedder:
                from fastembed import TextEmbedding  # Apache-2.0

                name = s.question_fallback_embedder
                if model_key(name) == "bge-m3" and name not in {m["model"] for m in TextEmbedding.list_supported_models()}:
                    from fastembed.common.model_description import ModelSource, PoolingType

                    TextEmbedding.add_custom_model(model=name, pooling=PoolingType.CLS, normalization=True, sources=ModelSource(hf=name),
                                                   dim=1024, model_file="onnx/model.onnx", additional_files=["onnx/model.onnx_data"])
                t0 = time.time()
                self._m = TextEmbedding(name, cache_dir=s.question_fallback_cache_dir)
                self.name = name
                log.info("question analytics: local embedder %s loaded in %.1fs", name, time.time() - t0)
            return self._m


_local = _Local()
_down_until = 0.0
_state_lock = threading.Lock()


def _unit(v) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(a))
    return a / n if n else a


def local_embed(texts: list[str]) -> list[np.ndarray]:
    prefix = "query: " if "e5" in model_key(get_settings().question_fallback_embedder) else ""
    return [_unit(v) for v in _local.get().embed([prefix + t for t in texts], batch_size=16)]


_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="q-embed")


def _main_with_deadline(texts: list[str]) -> list[np.ndarray]:
    """Circuit breaker: the retrieval client retries 429 with backoff for minutes (index/embeddings.py, untouched);
    analytics waits at most QUESTION_EMBED_TIMEOUT_S per 32 texts and then treats the main embedder as down. The
    abandoned call finishes in the background and still fills the shared disk cache."""
    from .questions import _embed

    s = get_settings()
    if not s.question_embed_timeout_s:
        return _embed(texts)
    fut = _pool.submit(_embed, texts)
    try:
        return fut.result(timeout=s.question_embed_timeout_s * max(1, math.ceil(len(texts) / 32)))
    except FutureTimeout as e:
        raise TimeoutError(f"main embedder slower than {s.question_embed_timeout_s}s (retrying 429?)") from e


def embed(texts: list[str]) -> tuple[list[np.ndarray], str]:
    """(unit vectors, model key). Main embedder first; on failure or timeout — the local fallback for the cool-down period."""
    global _down_until
    from .questions import _embed

    s = get_settings()
    if not s.question_fallback_embedder:
        return _embed(texts), main_model()
    if time.time() >= _down_until:
        try:
            return _main_with_deadline(texts), main_model()
        except Exception as e:  # noqa: BLE001
            with _state_lock:
                _down_until = time.time() + s.question_fallback_cooldown_s
            log.warning("question analytics: main embedder failed (%s), local %s for %ss", str(e)[:160], s.question_fallback_embedder,
                        s.question_fallback_cooldown_s)
    return local_embed(texts), model_key(s.question_fallback_embedder)


def status() -> dict:
    s = get_settings()
    return {"main": main_model(), "fallback": model_key(s.question_fallback_embedder) or None,
            "fallback_active": time.time() < _down_until, "thresholds": thresholds(),
            "fallback_thresholds": thresholds(s.question_fallback_embedder) if s.question_fallback_embedder else None}
