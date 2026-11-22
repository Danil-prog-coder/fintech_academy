"""Lexical channel: Russian/English BM25 as Qdrant sparse vectors (IDF applied by Qdrant, Modifier.IDF).

Exact tokens matter for this KB (FR-RET-03, FR-INP-04): filter operators (!>, >=, !=, <>), deal numbers
(2334-26), percentages (60%), times (17:30), phones and amounts are kept verbatim; words are stemmed.
"""

from __future__ import annotations

import re
import zlib
from collections import Counter

import snowballstemmer

_RU = snowballstemmer.stemmer("russian")
_EN = snowballstemmer.stemmer("english")

TOKEN_RE = re.compile(
    r"""
    (?P<op>!>|!<|>=|<=|<>|!=|==|=>|=<|[<>=|])           # filter operators and the in-list separator
    |(?P<phone>\+?\d[\d\s()-]{8,}\d)                     # phones
    |(?P<num>\d+(?:[.,:\-/]\d+)*%?)                      # numbers, dates, times, deal ids, percents
    |(?P<word>[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9_\-]*)   # words (hyphenated kept, e.g. БАРС-Офис)
    """,
    re.X,
)

STOP = set("""и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня еще нет о из ему
теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть
надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь
этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после над больше тот через эти
нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно
всю между это the a an of to in is are""".split())


def _stem(w: str) -> str:
    w = w.lower().replace("ё", "е")
    if re.search(r"[а-я]", w):
        return _RU.stemWord(w)
    return _EN.stemWord(w)


def tokenize(text: str) -> list[str]:
    toks: list[str] = []
    for m in TOKEN_RE.finditer(text):
        kind = m.lastgroup
        val = m.group(0)
        if kind == "op":
            toks.append("op:" + val)
        elif kind == "phone":
            toks.append("ph:" + re.sub(r"\D", "", val))
        elif kind == "num":
            toks.append("n:" + val.replace(",", "."))
            if val.endswith("%"):
                toks.append("n:" + val[:-1])
        else:
            low = val.lower()
            if low in STOP or len(low) < 2:
                if low == "in":
                    toks.append("op:in")
                continue
            if "-" in low:  # БАРС-Офис -> барс-офис + барс + офис
                toks.append(low)
                toks.extend(_stem(p) for p in low.split("-") if len(p) > 1)
            else:
                toks.append(_stem(low))
    return toks


def _hash(tok: str) -> int:
    return zlib.crc32(tok.encode("utf-8")) & 0x7FFFFFFF


def doc_sparse(text: str, avgdl: float, k1: float = 1.2, b: float = 0.75) -> tuple[list[int], list[float]]:
    toks = tokenize(text)
    dl = len(toks) or 1
    tf = Counter(toks)
    idx, vals = [], []
    acc: dict[int, float] = {}
    for t, f in tf.items():
        w = f * (k1 + 1) / (f + k1 * (1 - b + b * dl / max(avgdl, 1.0)))
        h = _hash(t)
        acc[h] = acc.get(h, 0.0) + w
    for h, w in acc.items():
        idx.append(h)
        vals.append(float(w))
    return idx, vals


def query_sparse(text: str) -> tuple[list[int], list[float]]:
    acc: dict[int, float] = {}
    for t in tokenize(text):
        h = _hash(t)
        # operators / exact numbers are strong signals for this KB
        weight = 2.0 if t.startswith(("op:", "n:", "ph:")) else 1.0
        acc[h] = max(acc.get(h, 0.0), weight)
    return list(acc.keys()), list(acc.values())
