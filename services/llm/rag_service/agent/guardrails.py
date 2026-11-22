"""Guardrails (Miro S88): code-enforced safety rules around the LLM agent (RK-2).

- explicit operator request detector, runs BEFORE the agent (FR-ESC-01);
- citation check: [N] -> real source of this dialog, quotes are exact substrings (FR-AGT-03, FR-GEN-02);
- groundedness of numbers/times/phones (FR-GEN-03);
- minimal evidence threshold (FR-CONF-02).
All functions are pure and unit-tested without an LLM (NFR-03).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- explicit operator request
_OP_WORDS = r"(оператор\w*|человек\w*|живо\w+\s+(?:человек\w*|специалист\w*|сотрудник\w*)|специалист\w*|сотрудник\w*\s+поддержк\w*|поддержк\w*|дежурн\w+)"
_ASK_VERBS = r"(позов\w*|позв\w*|соедин\w*|переключ\w*|перевед\w*|передай\w*|свяж\w*|связать\w*|нуж\w*|хочу|дайте|давай\w*|можно|пообщат\w*|поговор\w*)"
_FILTER_CTX = re.compile(r"(фильтр|сравнени|символ|!=|!>|>=|<=|<>|[<>=]\s*\d|оператор\w*\s+(?:фильтр|сравн|in\b))", re.I)


def is_operator_request(message: str) -> bool:
    """Fast keyword detector: 'оператор', 'человек', 'живой специалист', 'позовите сотрудника', button text."""
    t = (message or "").strip().lower().replace("ё", "е")
    if not t:
        return False
    if t in {"/operator", "оператор", "оператора", "человек", "человека", "связаться с поддержкой", "живой человек", "позовите человека"}:
        return True
    if _FILTER_CTX.search(t):
        return False  # «операторы фильтра» etc. — about filter syntax, not a handoff
    if re.search(rf"\b{_ASK_VERBS}\b.{{0,40}}\b{_OP_WORDS}", t):
        return True
    if re.search(r"\b(живо\w+\s+(человек|специалист|оператор)|позовите\s+сотрудника|с\s+оператором|оператора\s+пожалуйста)\b", t):
        return True
    if len(t.split()) <= 3 and re.search(r"\b(оператор\w*|человек\w*)\b", t):
        return True
    return False


# ---------------------------------------------------------------- citations
_NORM_RE = re.compile(r"[*_`#>]+|\s+")


def norm(text: str) -> str:
    t = (text or "").replace("ё", "е").replace("Ё", "Е")
    t = re.sub(r"[«»“”„\"']", '"', t)
    t = re.sub(r"[–—]", "-", t)
    t = _NORM_RE.sub(" ", t)
    return t.strip().lower()


CITE_RE = re.compile(r"\[(\d{1,2})\]")
NUMBER_RE = re.compile(r"(?<![\w\[])(\+?\d[\d\s()\-]{7,}\d|\d{1,2}:\d{2}|\d+(?:[.,]\d+)?\s?%|\d[\d\s]{2,}\d|\d+(?:[.,]\d+)?)(?![\w\]])")


@dataclass
class CheckResult:
    ok: bool
    problems: list[str] = field(default_factory=list)
    valid_citations: list[dict] = field(default_factory=list)
    removed_quotes: list[str] = field(default_factory=list)
    ungrounded_numbers: list[str] = field(default_factory=list)


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in NUMBER_RE.findall(text):
        v = re.sub(r"[\s()]", "", raw).replace(",", ".")
        v = v.rstrip("%")
        if re.fullmatch(r"\d{1,2}", v) and int(v) <= 12:
            continue  # step numbers, list markers, small counts
        out.add(v)
    return out


def numbers_in_sources(texts: list[str]) -> set[str]:
    s = set()
    for t in texts:
        s |= _numbers(t)
        s |= {re.sub(r"\D", "", x) for x in re.findall(r"\+?\d[\d\s()\-]{7,}\d", t)}
    return s


def ungrounded_numbers(text: str, allowed: set[str]) -> list[str]:
    """Numbers / times / phones of the answer text that are absent from the sources (FR-GEN-03)."""
    body = CITE_RE.sub(" ", text or "")
    body = re.sub(r"(?m)^\s*\d{1,2}[.)]\s", " ", body)
    out = []
    for num in _numbers(body):
        digits = re.sub(r"\D", "", num)
        if num not in allowed and digits not in allowed and not any(
                num in a or (digits and digits in re.sub(r"\D", "", a)) for a in allowed if len(num) >= 3):
            out.append(num)
    return out


_SID_GROUP_RE = re.compile(r"\[((?:[ST]\d{1,3})(?:\s*[,;]\s*(?:[ST]\d{1,3}|\d{1,2}))*)\]")


def normalize_markers(text: str, citations: list[dict], registry: dict) -> tuple[str, list[dict]]:
    """Models sometimes cite by source id («[S2]», «[S1, S2]») instead of [N]. Map ids to citation numbers
    (re-using an existing citation of the same source or adding a new one without a quote)."""
    cits = [dict(c) for c in (citations or []) if isinstance(c, dict)]
    # the model sometimes cites an image_id / chunk_id instead of the source id: map it to the registry entry
    for c in cits:
        sid = str(c.get("source_id", "")).strip()
        if sid and sid not in registry:
            for k, v in registry.items():
                if sid == v.get("chunk_id") or sid in (v.get("image_ids") or []):
                    c["source_id"] = k
                    break
    by_sid: dict[str, int] = {}
    for c in cits:
        try:
            by_sid.setdefault(str(c.get("source_id", "")).strip(), int(c.get("n")))
        except (TypeError, ValueError):
            continue
    used = {int(c["n"]) for c in cits if str(c.get("n", "")).isdigit() or isinstance(c.get("n"), int)}

    def repl(m: re.Match) -> str:
        out = []
        for tok in re.split(r"\s*[,;]\s*", m.group(1)):
            if tok.isdigit():
                out.append(f"[{tok}]")
                continue
            if tok not in registry:
                out.append(f"[{tok}]")  # unknown id: left as is, check_answer will reject it
                continue
            if tok not in by_sid:
                n = max(used | {0}) + 1
                used.add(n)
                by_sid[tok] = n
                cits.append({"n": n, "source_id": tok, "quote": ""})
            out.append(f"[{by_sid[tok]}]")
        return "".join(out)

    new_text = _SID_GROUP_RE.sub(repl, text or "")
    return new_text, cits


def check_answer(text: str, citations: list[dict], registry: dict, *, user_text: str = "") -> CheckResult:
    """Validate a grounded answer against the session source registry."""
    res = CheckResult(ok=True)
    markers = [int(x) for x in CITE_RE.findall(text or "")]
    by_n: dict[int, dict] = {}
    for c in citations or []:
        try:
            n = int(c.get("n"))
        except (TypeError, ValueError):
            continue
        by_n[n] = c
    if not markers and not by_n:
        res.ok = False
        res.problems.append("в ответе нет ссылок [N] на найденные фрагменты")
        return res
    for n in sorted(set(markers)):
        if n not in by_n:
            res.ok = False
            res.problems.append(f"маркер [{n}] есть в тексте, но не описан в citations")
    cited_texts: list[str] = []
    for n, c in sorted(by_n.items()):
        sid = str(c.get("source_id", "")).strip()
        src = registry.get(sid)
        if src is None:
            res.ok = False
            res.problems.append(f"[{n}] ссылается на {sid!r}, которого нет среди результатов инструментов этого диалога")
            continue
        quote = (c.get("quote") or "").strip()
        if quote and norm(quote) not in norm(src.get("text", "")):
            res.removed_quotes.append(quote)
            quote = ""  # FR-GEN-02: quotes absent from the source are cut
        cited_texts.append(src.get("text", ""))
        res.valid_citations.append({"n": n, "source_id": sid, "quote": quote})
    bad_ids = re.findall(r"\[([ST]\d{1,3})", text or "")
    if bad_ids:
        res.ok = False
        res.problems.append("в тексте ссылки на source_id, которых нет в результатах: " + ", ".join(sorted(set(bad_ids))))
    if markers and not any(c["n"] in markers for c in res.valid_citations):
        res.ok = False
        res.problems.append("ни один маркер [N] не указывает на реальный фрагмент")
    # numbers / times / phones must come from sources of this dialog (FR-GEN-03)
    allowed = numbers_in_sources(cited_texts + [s.get("text", "") for s in registry.values()] + [user_text])
    res.ungrounded_numbers = ungrounded_numbers(text or "", allowed)
    if res.ungrounded_numbers:
        res.ok = False
        res.problems.append("числа/время/телефоны отсутствуют в найденных фрагментах: " + ", ".join(sorted(res.ungrounded_numbers)))
    return res


def max_evidence(citations: list[dict], registry: dict) -> float:
    vals = []
    for c in citations:
        src = registry.get(c.get("source_id"))
        if src is not None:
            vals.append(src.get("score") if src.get("score") is not None else 0.0)
    return max(vals) if vals else 0.0


# ---------------------------------------------------------------- confidence (FR-CONF-01)

def confidence(*, evidence: float, gap: float, n_supporting: int, coverage: str, first_pass: bool,
               high: float, medium: float) -> tuple[float, str]:
    cov = {"full": 1.0, "partial": 0.5}.get(coverage, 0.0)
    score = 0.5 * evidence + 0.1 * min(max(gap, 0.0) / 0.3, 1.0) + 0.15 * min(n_supporting, 3) / 3 + 0.25 * cov
    if not first_pass:
        score -= 0.1
    score = round(max(0.0, min(1.0, score)), 3)
    level = "high" if score >= high else "medium" if score >= medium else "low"
    return score, level


# ---------------------------------------------------------------- diagram branches (FR-GEN-06)
_COND_Q = re.compile(r"услови|развилк|в каком случае|в каких случаях|маршрут|варианты\s+(?:прохожд|соглас)|когда\s+(?:нужн|требует)|от чего зависит", re.I)
# a decision line of «Правила переходов» (ingest/vision.py): v1 «- если Вопрос? — Да, …», v2 «- «Вопрос?» — Да → «…»»
_BRANCH_RE = re.compile(r"^-\s*(?:если\s+)?«?([^«»\n]+?\?)»?\s*[—–-]", re.M)
_W = re.compile(r"[a-zа-яё0-9]+", re.I)


def branch_gap(question: str, answer: str, cited: list[dict], min_share: float = 0.5) -> list[str]:
    """Decision questions of a cited process diagram that the answer does not mention, when the user asks about
    conditions / routes. [] when the question is not about conditions, no diagram with «Правила переходов» is cited,
    the diagram has fewer than 2 decisions, or the answer already covers at least `min_share` of them (a decision is
    covered when ≥ 60 % of its content words, compared by 5-letter stems, meet in one sentence of the answer).
    Generic: it reads the transitions the VLM wrote at indexing, so it works for any BPMN diagram, not for test cases."""
    if not _COND_Q.search(question or ""):
        return []
    conds: list[str] = []
    for src in cited:
        text = src.get("text") or ""
        if src.get("chunk_type") != "image" or "Правила переходов" not in text:
            continue
        for c in _BRANCH_RE.findall(text.split("Правила переходов", 1)[1]):
            c = c.strip()
            if c not in conds:
                conds.append(c)
    if len(conds) < 2:
        return []
    # a decision counts only when its words meet in ONE sentence / line of the answer: over the whole answer common
    # words («нужен» in «если нужен полный алгоритм», «обрат» in «обратитесь») made untouched decisions look covered
    segs = [{w[:5] for w in _W.findall(seg) if len(w) >= 3} for seg in re.split(r"[\n.!?;]+", norm(answer))]

    def covered(c: str) -> bool:
        words = {w[:5] for w in _W.findall(norm(c)) if len(w) >= 3}
        return bool(words) and any(len(words & have) / len(words) >= 0.6 for have in segs)

    missing = [c for c in conds if not covered(c)]
    return missing if (len(conds) - len(missing)) / len(conds) < min_share else []
