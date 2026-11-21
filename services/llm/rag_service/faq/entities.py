"""Key entities of a question for the FAQ equivalence check (FR-FAQ-04 step 3, FR-FAQ-01 homogeneity).

Entities: objects (document / registry / screen / process named in the question, matched by stem),
numbers and filter operators. Two questions can share a cached answer only when their entity sets are equal,
so «статусы в реестре техники» never gets the answer about «реестр мебели» (FR-GEN-05).
"""

from __future__ import annotations

import re

import snowballstemmer  # BSD

_stemmer = snowballstemmer.stemmer("russian")
_OBJECT_KW = (r"(?:реестр\w*|документ\w*|экран\w*|бп|бизнес-процесс\w*|процесс\w*|справочник\w*|форм[аеуыой]\w*|"
              r"журнал\w*|отч[её]т\w*|модул\w*|окн[оае]\w*|вкладк\w*|меню|кнопк\w*|пол[еяю]\w*)")
# the word after an object keyword is an object name only if it does not look like a verb/adverb
_VERBISH = re.compile(r"(?:ют|ут|ят|ат|ет|ит|ешь|ишь|ем|им|ется|ются|ится|ятся|ался|ались|ть|ться|ли|ло|ла|"
                      r"ал|ил|ел|но|ще|ее|ше|ого)$")
_STOP = {"для", "или", "как", "что", "где", "это", "этот", "этом", "мне", "меня", "надо", "нужно", "можно", "есть",
         "какие", "какой", "какая", "каких", "который", "которые", "при", "под", "над", "без", "все", "всех", "его",
         "она", "они", "там", "тут", "так", "уже", "если", "чтобы", "почему", "когда", "кто", "чем", "сделать",
         "работает", "работать", "выглядит", "выглядят", "найти", "перечислены", "перечислен", "быть", "бывают", "бывает",
         "также", "тоже", "теперь", "сейчас", "всегда", "этого", "этой", "того", "той", "свой", "свою", "своего"}
_GENERIC_TITLE = {"функциональн", "возможн", "работ", "инструкц", "документ", "раздел", "руководств", "пользовател",
                  "описан", "систем"}
_ABBR = {r"\bбо\b": "барс-офис", r"\bбц\b": "бизнес-центр", r"\bом\b": "офис-менеджер"}
_OPS_RE = re.compile(r"!>|>=|<=|<>|!=|(?<![!<>=])[<>](?!=)")
_NUM_RE = re.compile(r"\d+(?:[.,:\-/]\d+)*")


def stem(word: str) -> str:
    return _stemmer.stemWord(word.lower().replace("ё", "е"))


def _norm(text: str) -> str:
    t = (text or "").lower().replace("ё", "е")
    for pat, rep in _ABBR.items():
        t = re.sub(pat, rep, t)
    return t


def title_vocabulary(titles: list[str]) -> set[str]:
    """Distinctive stems of knowledge-base document titles («мебел», «командировк», «барс», «офис»)."""
    vocab: set[str] = set()
    for t in titles:
        for w in re.findall(r"[а-яa-z]{3,}", _norm(t)):
            st = stem(w)
            if w not in _STOP and st not in _GENERIC_TITLE and len(st) >= 3:
                vocab.add(st)
    return vocab


def extract_entities(text: str, vocab: set[str] | frozenset = frozenset()) -> dict[str, list[str]]:
    t = _norm(text)
    objects: set[str] = set()
    for m in re.finditer(_OBJECT_KW + r"\s+(?:[«\"'“]\s*)?([а-яa-z][а-яa-z\-]{2,})", t):
        w = m.group(1).strip("-")
        if w not in _STOP and (stem(w) in vocab or not _VERBISH.search(w)):
            objects.add(stem(w.split("-")[0]))
    for w in re.findall(r"[а-яa-z]{3,}", t):
        st = stem(w)
        if st in vocab:
            objects.add(st)
    numbers = set(_NUM_RE.findall(t))
    ops = set(_OPS_RE.findall(text or ""))
    return {"objects": sorted(objects), "numbers": sorted(numbers), "operators": sorted(ops)}


def same_entities(a: dict, b: dict) -> bool:
    return all(sorted(a.get(k) or []) == sorted(b.get(k) or []) for k in ("objects", "numbers", "operators"))


def entity_key(e: dict) -> str:
    return "|".join(",".join(sorted(e.get(k) or [])) for k in ("objects", "numbers", "operators"))
