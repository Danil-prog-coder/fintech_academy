"""parse_bo_link (FR-INP-03): deterministic parsing and repair of the product's internal links.

Host names, action and module codes come from the product file (`links` section). The document a link
points to is recognised by matching its transliterated slug against names found in the knowledge base
(document titles, section names, labels on screenshots) — there is no built-in list of documents.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote, urlsplit

from rapidfuzz import fuzz

from ..product import section

HOMOGLYPHS = {"А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M", "О": "O", "Р": "P", "Т": "T",
              "Х": "X", "а": "a", "с": "c", "е": "e", "о": "o", "р": "p", "х": "x", "у": "y"}


def hosts() -> dict[str, str]:
    return section("links").get("hosts") or {}


# multiple transliteration variants per Cyrillic letter
_VARIANTS = {
    "а": ["a"], "б": ["b"], "в": ["v", "w"], "г": ["g"], "д": ["d"], "е": ["e", "ye", "ee"], "ё": ["e", "yo"],
    "ж": ["zh", "j", "g"], "з": ["z"], "и": ["i"], "й": ["y", "i", "j"], "к": ["k"], "л": ["l"], "м": ["m"],
    "н": ["n"], "о": ["o"], "п": ["p"], "р": ["r"], "с": ["s"], "т": ["t"], "у": ["u"], "ф": ["f"],
    "х": ["kh", "h", "x"], "ц": ["ts", "c", "tc"], "ч": ["ch"], "ш": ["sh"], "щ": ["shch", "sch"], "ъ": [""],
    "ы": ["y", "i"], "ь": [""], "э": ["e"], "ю": ["yu", "iu", "ju"], "я": ["ya", "ia", "ja"],
}

def translit_simple(text: str) -> str:
    return "".join(_VARIANTS.get(ch, [ch])[0] for ch in text.lower() if ch.isalnum())


def _best_translit_score(slug: str, name: str) -> float:
    """Greedy alignment over transliteration variants: pick per-letter variant that best matches the slug."""
    s = slug.lower()
    out = []
    pos = 0
    for ch in name.lower():
        if not ch.isalnum():
            continue
        opts = _VARIANTS.get(ch, [ch])
        best = opts[0]
        for o in sorted(opts, key=len, reverse=True):
            if o and s.startswith(o, pos):
                best = o
                break
        out.append(best)
        pos += len(best)
    cand = "".join(out)
    return max(fuzz.ratio(s, cand), fuzz.ratio(s, translit_simple(name)))


@dataclass
class LinkAnalysis:
    original: str
    is_bo_link: bool
    host: str | None = None
    system: str | None = None
    action: str | None = None
    module: str | None = None
    document_slug: str | None = None
    document_guess: str | None = None
    document_candidates: list[dict] = field(default_factory=list)
    record_id: str | None = None
    problems: list[str] = field(default_factory=list)
    normalized_url: str | None = None
    damaged: bool = False
    search_hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def parse_bo_link(url: str, known_names: list[str] | None = None) -> LinkAnalysis:
    raw = (url or "").strip().strip("<>\"'«»")
    res = LinkAnalysis(original=raw, is_bo_link=False)
    if not re.match(r"^https?://", raw):
        raw2 = "https://" + raw
    else:
        raw2 = raw
    parts = urlsplit(raw2)
    host = parts.hostname or ""
    res.host = host
    cfg = section("links")
    known = hosts()
    if host not in known:
        res.problems.append("ссылка не относится к внутренним системам (" + (" / ".join(known) or "хосты не настроены") + ")")
        return res
    res.is_bo_link = True
    res.system = known[host]
    res.search_hints = list(cfg.get("search_hints") or [])
    path = parts.path or "/"
    if "//" in raw2.split("://", 1)[1]:
        res.problems.append("в адресе лишний слэш «//» после домена")
    frag = unquote(parts.fragment or "")
    tokens = frag.split("&") if frag else []
    if any(t == "" for t in tokens):
        res.problems.append("в параметрах есть пустые элементы («&&» или «&» в конце)")
    params: dict[str, str] = {}
    positional: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "":
            i += 1
            continue
        if "=" in t and t not in ("=",):
            k, v = t.split("=", 1)
            params[k] = v
        elif i + 2 < len(tokens) and tokens[i + 1] == "=":
            # broken pair "id&=&VALUE"
            res.problems.append(f"сломанный параметр «{t}&=&…»: ожидалось «{t}=…»")
            params[t] = tokens[i + 2]
            i += 3
            continue
        else:
            positional.append(t)
        i += 1
    if positional:
        res.action = positional[0]
    if len(positional) > 1:
        res.module = positional[1]
    if len(positional) > 2:
        res.document_slug = positional[2]
    rid = params.get("id")
    if rid is not None:
        bad = [(idx, ch) for idx, ch in enumerate(rid) if not ch.isascii()]
        if bad:
            desc = ", ".join(f"«{ch}» ({unicodedata.name(ch, '?').lower().replace('cyrillic', 'кириллическая').replace('capital letter', 'заглавная').replace('small letter', 'строчная')}, U+{ord(ch):04X}) в позиции {idx + 1}" for idx, ch in bad)
            res.problems.append(f"в идентификаторе записи есть не-латинские символы: {desc} — вероятно, кириллическая буква вместо латинской")
            rid = "".join(HOMOGLYPHS.get(ch, ch) for ch in rid)
        if rid and cfg.get("id_pattern") and not re.fullmatch(cfg["id_pattern"], rid):
            res.problems.append("идентификатор записи не похож на " + cfg.get("id_description", "ожидаемый формат"))
        res.record_id = rid
    if res.document_slug:
        names = list(dict.fromkeys(known_names or []))
        scored = sorted(((round(_best_translit_score(res.document_slug, n), 1), n) for n in names), reverse=True)[:3]
        res.document_candidates = [{"name": n, "score": sc} for sc, n in scored]
        if scored and scored[0][0] >= 75:
            res.document_guess = scored[0][1]
    res.damaged = bool(res.problems)
    # normalized url
    q = [x for x in (res.action, res.module, res.document_slug) if x]
    frag_new = "&".join(q + ([f"id={res.record_id}"] if res.record_id else []))
    res.normalized_url = f"https://{host}/#{frag_new}" if frag_new else f"https://{host}{re.sub('/+', '/', path)}"
    actions, modules = cfg.get("actions") or {}, cfg.get("modules") or {}
    if res.action in actions:
        res.action = f"{res.action} — {actions[res.action]}"
    if res.module in modules:
        res.module = f"{res.module} — {modules[res.module]}"
    return res


def extract_links(text: str) -> list[str]:
    known = "|".join(re.escape(h) for h in hosts())
    return re.findall(rf"(?:https?://)?(?:{known})[^\s<>»\"]*", text) if known else []
