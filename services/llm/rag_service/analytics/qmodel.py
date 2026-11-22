"""Trained question classifier: softmax regression on the question embedding + a few lexical features (numpy only).

Heads: `intent` (question / error / operator / smalltalk), `on_topic`, `topic` (admin taxonomy), `sentiment`
(negative / neutral / positive) and `urgency` (urgent / normal). Each prediction carries its probability; the caller
(analytics/questions.py) uses a head only when it is confident (QUESTION_MODEL_MIN_CONF) and falls back to the async
LLM classifier (topic) or the keyword rules otherwise. No extra LLM call: the embedding is the one retrieval already
computed (disk cache).

The weights live in `qmodel.npz` next to this file (~100 KB, float16), trained offline by
eval/clustering/train_classifier.py on the golden-set log and the synthetic log; the file records the embedding
model and dimension, and the classifier is skipped when they do not match the running embedder.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

MODEL_FILE = Path(__file__).with_name("qmodel.npz")
HEADS = ("intent", "on_topic", "topic", "sentiment", "urgency")
INTENTS = ("question", "error", "operator", "smalltalk")

_URGENT = re.compile(r"срочн|горит|asap|немедленно|прямо сейчас|как можно скорее|побыстрее|быстрее|до вечера|до конца дня|"
                     r"сегодня надо|руководител\w* ждёт|руководител\w* ждет|блокирует|стоит работа|не могу работать|!!", re.I)
_NEGATIVE = re.compile(r"опять|снова|сколько можно|достал|бесит|ужас|бред|ерунд|фигн|черт|чёрт|нормально (?:ответ|объясн)|"
                       r"ничего не понятно|невозможно|отвратительн|бесполезн|туп\w+|задолбал|надоел|какого|почему опять", re.I)
_POSITIVE = re.compile(r"спасибо|благодар|спс|пожалуйста|будьте добры|отлично|супер|класс|выручил|помогло|хорошего дня|"
                       r"заранее|😊|🙏|👍|❤", re.I)
_CODE = re.compile(r"[A-Za-z]{2,6}[-_ ]?\d{3,5}|ошибк\w*\s*[:№#]?\s*[45]\d\d", re.I)
N_LEX = 14


def lexical(text: str, rule_intent: str | None) -> np.ndarray:
    """Cheap text features the embedding misses: rule intent, error codes, tone and urgency markers, shape."""
    t = text or ""
    letters = [c for c in t if c.isalpha()]
    f = [float(rule_intent == x) for x in INTENTS]
    f += [float(bool(_CODE.search(t))), float(bool(_URGENT.search(t))), float(bool(_NEGATIVE.search(t))),
          float(bool(_POSITIVE.search(t))), min(t.count("!"), 3) / 3, float("?" in t),
          (sum(c.isupper() for c in letters) / len(letters)) if len(letters) >= 8 else 0.0,
          float(bool(letters) is False), min(math.log1p(len(t.split())), 4) / 4, float(bool(re.search(r"[a-z]{4,}", t)) and not re.search(r"[а-яё]", t, re.I))]
    return np.asarray(f, dtype=np.float32)


def features(vec, text: str, rule_intent: str | None) -> np.ndarray:
    v = np.asarray(vec, dtype=np.float32)
    v = v / (float(np.linalg.norm(v)) or 1.0)
    return np.concatenate([v, lexical(text, rule_intent)])


# ------------------------------------------------------------------------------------------------ training (numpy)
def train_head(X: np.ndarray, y: list[str], classes: list[str] | None = None, l2: float = 1e-3, epochs: int = 400,
               lr: float = 0.05, balanced: bool = True) -> dict:
    """Multinomial logistic regression, full-batch Adam with L2. Returns {"classes", "W", "b"}."""
    classes = classes or sorted(set(y))
    idx = {c: i for i, c in enumerate(classes)}
    yi = np.array([idx[v] for v in y])
    n, d = X.shape
    k = len(classes)
    Y = np.eye(k, dtype=np.float32)[yi]
    cnt = np.bincount(yi, minlength=k).astype(np.float32)
    w_s = (n / (k * np.maximum(cnt, 1)))[yi] if balanced else np.ones(n, dtype=np.float32)
    w_s = (w_s / w_s.sum()).astype(np.float32)
    W = np.zeros((d, k), dtype=np.float32)
    b = np.zeros(k, dtype=np.float32)
    mW, vW, mb, vb = np.zeros_like(W), np.zeros_like(W), np.zeros_like(b), np.zeros_like(b)
    for t in range(1, epochs + 1):
        Z = X @ W + b
        Z -= Z.max(1, keepdims=True)
        P = np.exp(Z)
        P /= P.sum(1, keepdims=True)
        G = (P - Y) * w_s[:, None]
        gW = X.T @ G + l2 * W
        gb = G.sum(0)
        for p, g, m, v in ((W, gW, mW, vW), (b, gb, mb, vb)):
            m *= 0.9
            m += 0.1 * g
            v *= 0.999
            v += 0.001 * g * g
            p -= lr * (m / (1 - 0.9 ** t)) / (np.sqrt(v / (1 - 0.999 ** t)) + 1e-8)
    return {"classes": list(classes), "W": W, "b": b}


def predict_head(head: dict, X: np.ndarray) -> tuple[list[str], np.ndarray]:
    Z = X @ head["W"].astype(np.float32) + head["b"].astype(np.float32)
    Z -= Z.max(1, keepdims=True)
    P = np.exp(Z)
    P /= P.sum(1, keepdims=True)
    return [head["classes"][i] for i in P.argmax(1)], P.max(1)


def save(heads: dict[str, dict], meta: dict, path: Path = MODEL_FILE) -> None:
    arrays = {}
    for name, h in heads.items():
        arrays[f"{name}__W"] = h["W"].astype(np.float16)
        arrays[f"{name}__b"] = h["b"].astype(np.float32)
    meta = {**meta, "heads": {n: h["classes"] for n, h in heads.items()}}
    np.savez_compressed(path, meta=np.frombuffer(json.dumps(meta, ensure_ascii=False).encode(), dtype=np.uint8), **arrays)


def load(path: Path = MODEL_FILE) -> tuple[dict[str, dict], dict] | None:
    if not path.exists():
        return None
    z = np.load(path)
    meta = json.loads(bytes(z["meta"]).decode())
    heads = {n: {"classes": cl, "W": z[f"{n}__W"].astype(np.float32), "b": z[f"{n}__b"]} for n, cl in meta["heads"].items()}
    return heads, meta


# ------------------------------------------------------------------------------------------------ runtime
class QuestionModel:
    def __init__(self, path: Path = MODEL_FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._loaded = False
        self.heads: dict[str, dict] = {}
        self.meta: dict = {}

    def _ensure(self) -> None:
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            try:
                got = load(self.path)
            except Exception as e:  # noqa: BLE001
                log.warning("question model not loaded: %s", e)
                got = None
            if got:
                self.heads, self.meta = got

    def ready(self, dim: int) -> bool:
        self._ensure()
        return bool(self.heads) and int(self.meta.get("dim") or 0) == dim

    def predict(self, vec, text: str, rule_intent: str | None, topics: list[str] | None = None) -> dict[str, tuple[str, float]]:
        """{head: (label, probability)}; {} when the model is missing or built for another embedder."""
        v = np.asarray(vec, dtype=np.float32)
        if not self.ready(v.shape[-1]):
            return {}
        x = features(v, text, rule_intent)[None, :]
        out: dict[str, tuple[str, float]] = {}
        for name, h in self.heads.items():
            if x.shape[1] != h["W"].shape[0]:
                continue
            if name == "topic" and topics:  # the taxonomy is admin-editable: only topics that still exist
                keep = [i for i, c in enumerate(h["classes"]) if c in topics]
                if not keep:
                    continue
                h = {"classes": [h["classes"][i] for i in keep], "W": h["W"][:, keep], "b": h["b"][keep]}
            lab, p = predict_head(h, x)
            out[name] = (lab[0], round(float(p[0]), 4))
        return out


_model: QuestionModel | None = None


def get_model() -> QuestionModel:
    global _model
    if _model is None:
        _model = QuestionModel()
    return _model
