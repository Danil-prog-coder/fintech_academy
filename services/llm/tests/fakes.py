"""Deterministic fakes shared by the new tests: bag-of-stems embeddings (no network)."""

import hashlib
import re

import numpy as np

from rag_service.faq.entities import stem

DIM = 256


def fake_vec(text: str) -> list[float]:
    v = np.zeros(DIM, dtype=np.float32)
    for w in re.findall(r"[а-яёa-z0-9]{3,}", text.lower()):
        h = int(hashlib.md5(stem(w).encode()).hexdigest(), 16)
        v[h % DIM] += 1.0
    n = float(np.linalg.norm(v)) or 1.0
    return (v / n).tolist()


class FakeEmbedder:
    model = "fake-bow"
    is_e5 = False

    def _embed(self, texts):
        return [fake_vec(t) for t in texts]

    def embed_documents(self, texts):
        return self._embed(texts)

    def embed_query(self, text):
        return fake_vec(text)
