"""validate_filter (FR-INP-04): deterministic check of the product's filter syntax.

The reference (supported and unsupported operators, date format, list syntax) is structured data from
the product file (`filters` section of config/product.yaml), built from the documentation. Fixes are
suggested ONLY from the documented syntax — the tool never invents operators.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..core.product import section


def reference() -> dict:
    """Filter syntax reference of the product; empty when the product file has no `filters` section."""
    return section("filters")


def _ops() -> dict:
    return reference().get("column_operators") or {}


def _unsupported() -> dict:
    return reference().get("unsupported") or {}


# order matters: compound operators first
OP_RE = re.compile(r"!>|!<|>=|=>|<=|=<|<>|==|!=|>|<|=")
NUM_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")
DATE_OK_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
DATE_ANY_RE = re.compile(r"^(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})$")


@dataclass
class FilterCheck:
    expression: str
    valid: bool
    kind: str  # column_compare | manual_in | empty_in | unknown
    operator: str | None = None
    value: str | None = None
    value_type: str | None = None
    problems: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    search_hints: list[str] = field(default_factory=list)
    supported_operators: list[str] = field(default_factory=lambda: list(_ops()))

    def to_dict(self) -> dict:
        return asdict(self)


def _value_type(v: str) -> str:
    v = v.strip().strip("\"'«»")
    if NUM_RE.match(v):
        return "number"
    if DATE_OK_RE.match(v):
        return "date"
    if DATE_ANY_RE.match(v):
        return "date_bad_format"
    return "text"


def _alternatives(op: str, value: str, vtype: str) -> list[str]:
    v = value.strip()
    alts: list[str] = []
    editor = reference().get("editor_hint")
    is_int = bool(re.fullmatch(r"-?\d+", v))
    if op in ("!>", "<=", "=<"):
        if is_int:
            alts.append(f"«< {int(v) + 1}» — для целых значений это то же самое, что «не больше {v}»")
        alts.append(f"«< {v}» — строго меньше {v} (без самого значения {v})")
        if editor:
            alts.append(f"{editor}: группа «или» с условиями «< {v}» и «= {v}»")
    elif op in ("!<", ">=", "=>"):
        if is_int:
            alts.append(f"«> {int(v) - 1}» — для целых значений это то же самое, что «не меньше {v}»")
        alts.append(f"«> {v}» — строго больше {v}")
        if editor:
            alts.append(f"{editor}: группа «или» с условиями «> {v}» и «= {v}»")
    elif op == "<>":
        alts.append(f"«!= {v}»")
    elif op == "==":
        alts.append(f"«= {v}»")
    return alts


def validate_filter(expression: str) -> FilterCheck:
    expr = (expression or "").strip().strip("\"'«»“”")
    ref = reference()
    if not ref:
        return FilterCheck(expression=expr, valid=False, kind="unknown",
                           problems=["справочник синтаксиса фильтров не настроен — проверь по документации через search_docs"])
    refs = list(ref.get("search_hints") or [])
    supported = "», «".join(_ops())
    unsupported = _unsupported()
    date_format = ref.get("date_format", "dd.mm.yyyy")
    text_ops = ref.get("text_operators") or ["=", "!="]
    # manual list filter: "in A|B|C"
    if re.match(r"^in\b", expr, re.I) or re.match(r"^in[^\s]", expr, re.I):
        chk = FilterCheck(expression=expr, valid=True, kind="manual_in", search_hints=refs)
        if expr.lower() in ("in", "in _-_") or expr == "in ":
            chk.kind = "empty_in"
            return chk
        if not re.match(r"^in\s", expr, re.I):
            chk.valid = False
            chk.problems.append("после «in» обязательно должен следовать пробел")
            fixed = "in " + expr[2:]
            chk.suggestions.append(f"«{fixed}»")
            expr = fixed
        body = expr[3:]
        if re.search(r"\s\||\|\s", body):
            chk.valid = False
            chk.problems.append("между значениями и символом «|» не должно быть пробелов")
            chk.suggestions.append("«in " + re.sub(r"\s*\|\s*", "|", body.strip()) + "»")
        if "," in body and "|" not in body:
            chk.valid = False
            chk.problems.append("в фильтре по столбцу значения перечисляются через «|», а не через запятую")
            chk.suggestions.append("«in " + "|".join(x.strip() for x in body.split(",")) + "»")
        return chk
    m = OP_RE.search(expr)
    if not m:
        return FilterCheck(expression=expr, valid=False, kind="unknown",
                           problems=[f"не найден оператор сравнения; поддерживаются только «{supported}» и ручной фильтр «in A|B|C»"],
                           search_hints=refs)
    op = m.group(0)
    value = expr[m.end():].strip()
    head = expr[:m.start()].strip()
    vtype = _value_type(value) if value else "empty"
    chk = FilterCheck(expression=expr, valid=True, kind="column_compare", operator=op, value=value, value_type=vtype,
                      search_hints=refs)
    if head:
        chk.problems.append(f"перед оператором стоит «{head}»: в поле фильтра столбца пишется только оператор и значение")
        chk.valid = False
    if op in unsupported or op not in _ops():
        chk.valid = False
        chk.problems.append(f"оператор «{op}» не поддерживается: {unsupported.get(op, 'его нет в документации')}. "
                            f"Для фильтрации по столбцам доступны только «{supported}»")
        chk.suggestions.extend(_alternatives(op, value, vtype))
    if vtype == "empty":
        chk.valid = False
        chk.problems.append("не указано значение после оператора")
    elif vtype == "date_bad_format":
        chk.valid = False
        chk.problems.append(f"дата должна быть в формате {date_format}")
        parts = re.split(r"[./-]", value)
        if len(parts) == 3:
            if len(parts[0]) == 4:
                y, mo, d = parts
            else:
                d, mo, y = parts
            if len(y) == 2:
                y = "20" + y
            chk.suggestions.append(f"«{op if op in _ops() else '<'} {int(d):02d}.{int(mo):02d}.{y}»")
    elif vtype == "text" and op in _ops() and op not in text_ops:
        chk.valid = False
        chk.problems.append("к текстовым значениям применимы только «" + "» и «".join(text_ops) + f"»; «{op}» — для чисел и дат")
    return chk


def extract_filter_expressions(text: str) -> list[str]:
    """Pull candidate filter expressions out of a user message (quoted or operator+value)."""
    found = re.findall(r"[«\"“']([^»\"”']{1,60})[»\"”']", text)
    out = [f for f in found if OP_RE.search(f) or re.match(r"^in\b", f.strip(), re.I)]
    if not out:
        out = [m.group(0).strip() for m in re.finditer(r"(!>|!<|>=|=>|<=|=<|<>|==|!=|>|<|=)\s*[\w.,\-]+", text)]
    return out
