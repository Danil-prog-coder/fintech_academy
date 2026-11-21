"""DOCX parser (FR-ING-01) on python-docx (MIT).

Keeps: heading hierarchy (Heading N styles, or numbered bold headings as a fallback), nested
numbered/bulleted lists (numPr + numbering.xml formats, or "List Number N" styles), callouts
(Confluence panels exported as 1x1 tables, Quote styles, shaded paragraphs), tables, and inline
images saved to disk with an anchor at the paragraph where they appear.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from .blocks import Block, ParsedDocument
from .noise import is_noise_line
from .util import slugify

HEADING_STYLE_RE = re.compile(r"^(Heading|Заголовок)\s*(\d)$", re.I)
LIST_STYLE_RE = re.compile(r"^List (Number|Bullet|Paragraph)\s*(\d)?$", re.I)
NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,3})\.?\s+[А-ЯЁA-Z]")
CALLOUT_STYLES = {"quote", "intense quote", "цитата", "выделенная цитата"}


def _roman(n: int) -> str:
    vals = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


class _Numbering:
    """Resolves numId/ilvl -> numFmt and keeps running counters to render list markers."""

    def __init__(self, document):
        self.formats: dict[tuple[str, int], str] = {}
        self.counters: dict[str, list[int]] = {}
        try:
            numbering = document.part.numbering_part.element
        except Exception:
            return
        abstract: dict[str, dict[int, str]] = {}
        for an in numbering.findall(qn("w:abstractNum")):
            aid = an.get(qn("w:abstractNumId"))
            lv = {}
            for lvl in an.findall(qn("w:lvl")):
                ilvl = int(lvl.get(qn("w:ilvl")))
                fmt = lvl.find(qn("w:numFmt"))
                lv[ilvl] = fmt.get(qn("w:val")) if fmt is not None else "decimal"
            abstract[aid] = lv
        for num in numbering.findall(qn("w:num")):
            nid = num.get(qn("w:numId"))
            a = num.find(qn("w:abstractNumId"))
            if a is None:
                continue
            for ilvl, fmt in abstract.get(a.get(qn("w:val")), {}).items():
                self.formats[(nid, ilvl)] = fmt

    def marker(self, num_id: str, ilvl: int, fmt: str | None = None) -> str:
        fmt = fmt or self.formats.get((num_id, ilvl), "decimal")
        c = self.counters.setdefault(num_id, [0] * 9)
        c[ilvl] += 1
        for d in range(ilvl + 1, 9):
            c[d] = 0
        n = c[ilvl]
        if fmt == "bullet":
            return "-"
        if fmt in ("lowerLetter", "upperLetter"):
            ch = chr(96 + ((n - 1) % 26) + 1)
            return (ch.upper() if fmt == "upperLetter" else ch) + "."
        if fmt in ("lowerRoman", "upperRoman"):
            r = _roman(n)
            return (r.upper() if fmt == "upperRoman" else r) + "."
        return f"{n}."


def _iter_body(document):
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _left_indent_twips(p: Paragraph) -> int:
    ppr = p._p.pPr
    if ppr is None:
        return 0
    ind = ppr.find(qn("w:ind"))
    if ind is None:
        return 0
    for attr in ("w:left", "w:start"):
        v = ind.get(qn(attr))
        if v and v.lstrip("-").isdigit():
            return int(v)
    return 0


def _is_shaded(p: Paragraph) -> bool:
    ppr = p._p.pPr
    return ppr is not None and ppr.find(qn("w:shd")) is not None and (ppr.find(qn("w:shd")).get(qn("w:fill")) or "auto").lower() not in ("auto", "ffffff")


def _paragraph_text(p: Paragraph) -> str:
    parts = []
    for run in p.runs:
        t = run.text
        if not t:
            continue
        if run.bold and t.strip():
            t = f"**{t.strip()}** " if not t.endswith(" ") else f"**{t.strip()}** "
        parts.append(t)
    text = "".join(parts) if parts else p.text
    text = re.sub(r"\*\*\s*\*\*", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _images_of(p: Paragraph, document, images_dir: Path, doc_id: str, counter: list[int]) -> list[str]:
    paths = []
    for blip in p._p.iter(qn("a:blip")):
        rid = blip.get(qn("r:embed"))
        if not rid or rid not in document.part.related_parts:
            continue
        part = document.part.related_parts[rid]
        counter[0] += 1
        ext = Path(getattr(part, "partname", "img.png")).suffix or ".png"
        out = images_dir / doc_id / f"img{counter[0]:03d}{ext}"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(part.blob)
        paths.append(str(out.resolve()))
    return paths


def _table_rows(t: Table) -> list[list[str]]:
    rows = []
    for r in t.rows:
        cells = []
        prev = None
        for c in r.cells:
            txt = " ".join(x.text.strip() for x in c.paragraphs if x.text.strip())
            if c._tc is prev:  # horizontally merged cell repeated by python-docx
                continue
            prev = c._tc
            cells.append(txt.replace("|", "/"))
        rows.append(cells)
    return rows


def parse_docx(path: str | Path, images_dir: str | Path) -> ParsedDocument:
    path = Path(path)
    images_dir = Path(images_dir)
    document = Document(str(path))
    doc_id = slugify(path.stem)
    numbering = _Numbering(document)
    style_counters: dict[int, int] = {}
    blocks: list[Block] = []
    warnings: list[str] = []
    title = (document.core_properties.title or "").strip()
    img_counter = [0]
    list_depth_indent: int = 0

    for item in _iter_body(document):
        if isinstance(item, Table):
            rows = _table_rows(item)
            if len(rows) == 1 and len(rows[0]) == 1 or (len(rows) >= 1 and all(len(r) == 1 for r in rows)):
                # Confluence panel / note exported as a single-column table -> callout
                text = "\n".join(r[0] for r in rows if r and r[0])
                if text and not is_noise_line(text):
                    blocks.append(Block("callout", text, indent=list_depth_indent))
            elif rows:
                blocks.append(Block("table", rows=rows, indent=list_depth_indent))
            continue
        p: Paragraph = item
        style = (p.style.name if p.style is not None else "") or ""
        text = _paragraph_text(p)
        imgs = _images_of(p, document, images_dir, doc_id, img_counter)
        if style.lower() == "title" and text:
            title = title or text
            continue
        if text and is_noise_line(text):
            continue
        hm = HEADING_STYLE_RE.match(style)
        plain = text.replace("**", "").strip()
        if hm and plain:
            blocks.append(Block("heading", plain, level=int(hm.group(2)) + 1))
            list_depth_indent = 0
            style_counters.clear()
        elif plain and NUMBERED_HEADING_RE.match(plain) and text.startswith("**") and len(plain) < 90 and not plain.endswith((".", ":", ";")):
            num = NUMBERED_HEADING_RE.match(plain).group(1)
            blocks.append(Block("heading", plain, level=num.count(".") + 2))
            list_depth_indent = 0
        elif plain:
            ppr = p._p.pPr
            numpr = ppr.find(qn("w:numPr")) if ppr is not None else None
            lm = LIST_STYLE_RE.match(style)
            if numpr is not None and numpr.find(qn("w:numId")) is not None:
                nid = numpr.find(qn("w:numId")).get(qn("w:val"))
                il = numpr.find(qn("w:ilvl"))
                ilvl = int(il.get(qn("w:val"))) if il is not None else 0
                marker = numbering.marker(nid, ilvl)
                blocks.append(Block("list_item", text, marker=marker, indent=ilvl * 4))
                list_depth_indent = ilvl * 4 + 4
            elif lm and lm.group(1).lower() != "paragraph":
                lvl = int(lm.group(2) or 1) - 1
                if lm.group(1).lower() == "bullet":
                    marker = "-"
                else:
                    style_counters[lvl] = style_counters.get(lvl, 0) + 1
                    for d in list(style_counters):
                        if d > lvl:
                            style_counters[d] = 0
                    n = style_counters[lvl]
                    marker = f"{n}." if lvl == 0 else (f"{chr(96 + n)}." if lvl == 1 else f"{_roman(n)}.")
                blocks.append(Block("list_item", text, marker=marker, indent=lvl * 4))
                list_depth_indent = lvl * 4 + 4
            elif style.lower() in CALLOUT_STYLES or _is_shaded(p):
                ind = 4 if _left_indent_twips(p) >= 360 else 0
                blocks.append(Block("callout", text, indent=ind if ind else 0))
            else:
                left = _left_indent_twips(p)
                ind = max(1, round(left / 360)) * 2 if left >= 300 else 0
                if ind == 0:
                    list_depth_indent = 0
                blocks.append(Block("paragraph", text, indent=ind))
        for ip in imgs:
            blocks.append(Block("image", image_path=ip, alt=plain[:80] if plain else "Изображение", indent=0))
        if not plain and not imgs and style.lower().startswith("list"):
            warnings.append("empty list paragraph (lost content?)")

    if not title:
        first_h = next((b for b in blocks if b.kind == "heading"), None)
        title = path.stem
        if first_h and first_h.level == 2 and not NUMBERED_HEADING_RE.match(first_h.text):
            title = first_h.text
    return ParsedDocument(title=title, doc_id=doc_id, source_file=path.name, blocks=blocks, warnings=warnings)
