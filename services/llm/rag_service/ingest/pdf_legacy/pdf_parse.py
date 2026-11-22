"""PDF parser. Produces the same Block list as parse_docx()."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pdfplumber

from .headings import (
    NUMBERED_HEADING_RE,
    match_toc_entry,
    normalize_spaces,
    parse_toc_text,
    short_doc_title,
)
from .images import extract_pdf_images
from .models import Block, TocEntry
from .noise import (
    is_in_header_footer_band,
    is_noise_text,
    is_toc_leader_line,
)

LIST_START_RE = re.compile(
    r"""^(
        [•●○▪►‣·▪]\s+
        |[-–—]\s+
        |\d+[.)]\s+
        |[a-zа-я][.)]\s+
        |[ivxIVX]+[.)]\s+
        |\(\d+\)\s+
        |[oо]\s+          # Confluence nested-list marker (Courier "o")
    )""",
    re.VERBOSE,
)

# Light-blue / grey callout fills used in these Confluence/Word exports
CALLOUT_COLORS = {
    (0.875, 0.937, 0.992),
    (0.87, 0.94, 0.99),
}


LATIN_SLUGS = {
    "функциональные_возможности_работы_с_барс_офисом": "bars_office",
    "барс_офис": "bars_office",
    "барс-офис": "bars_office",
    "бп_командировка": "bp_trip",
    "бп-командировка": "bp_trip",
    "реестр_мебели": "furniture",
    "реестр-мебели": "furniture",
}


def _doc_slug(*names: str) -> str:
    for name in names:
        slug = re.sub(r"[^a-zA-Zа-яА-Я0-9]+", "_", name or "").strip("_").lower()
        hyphen = slug.replace("_", "-")
        if slug in LATIN_SLUGS:
            return LATIN_SLUGS[slug]
        if hyphen in LATIN_SLUGS:
            return LATIN_SLUGS[hyphen]
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", names[0] if names else "doc").strip("_").lower()
    return slug[:40] or "doc"


def _is_bold(fontname: str | None) -> bool:
    name = fontname or ""
    return "Bold" in name or "bold" in name or "-Bd" in name


def _group_lines(words: list[dict], y_tol: float = 3.0) -> list[dict]:
    """Cluster words into visual lines, left-to-right."""
    if not words:
        return []
    words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    lines: list[list[dict]] = []
    current: list[dict] = [words[0]]
    current_top = words[0]["top"]
    for w in words[1:]:
        if abs(w["top"] - current_top) <= y_tol:
            current.append(w)
        else:
            lines.append(current)
            current = [w]
            current_top = w["top"]
    lines.append(current)

    result = []
    for ws in lines:
        ws = sorted(ws, key=lambda w: w["x0"])
        text = normalize_spaces(" ".join(w["text"] for w in ws))
        sizes = [float(w.get("size") or 0) for w in ws]
        fonts = [w.get("fontname") or "" for w in ws]
        # majority font / max size (headings use a single size)
        size = max(sizes) if sizes else 0
        # prefer a bold font name if present
        font = next((f for f in fonts if _is_bold(f)), fonts[0] if fonts else "")
        result.append(
            {
                "text": text,
                "top": min(w["top"] for w in ws),
                "bottom": max(w["bottom"] for w in ws),
                "x0": min(w["x0"] for w in ws),
                "x1": max(w["x1"] for w in ws),
                "size": size,
                "fontname": font,
                "words": ws,
            }
        )
    return result


def _line_to_type(line: dict, toc: list[TocEntry], prev_heading: dict | None) -> str:
    text = line["text"]
    size = line["size"]
    bold = _is_bold(line["fontname"])

    # Heading continuation (wrapped 6.3 title etc.)
    if (
        prev_heading is not None
        and bold
        and abs(size - prev_heading["size"]) <= 0.6
        and size >= 13
        and not NUMBERED_HEADING_RE.match(text)
        and not LIST_START_RE.match(text)
        and (line["top"] - prev_heading["bottom"]) <= size * 1.8
        and len(text.split()) <= 12
    ):
        return "heading_cont"

    if bold and size >= 13:
        if NUMBERED_HEADING_RE.match(text) or match_toc_entry(text, toc):
            return "heading"
        # unnumbered but large bold on a short line: only heading if TOC says so
        if size >= 15 and len(text.split()) <= 12 and not LIST_START_RE.match(text):
            # cover title or "Table of Contents" already filtered
            return "heading" if match_toc_entry(text, toc) else "title"

    if NUMBERED_HEADING_RE.match(text) and match_toc_entry(text, toc) and bold:
        return "heading"

    if LIST_START_RE.match(text):
        return "list_item"

    return "paragraph"


def _is_callout_line(line: dict, callout_rects: list[tuple]) -> bool:
    cx = (line["x0"] + line["x1"]) / 2
    cy = (line["top"] + line["bottom"]) / 2
    for x0, top, x1, bottom in callout_rects:
        if x0 <= cx <= x1 and top <= cy <= bottom:
            return True
    return False


def _collect_callout_rects(page) -> list[tuple[float, float, float, float]]:
    """Large filled rectangles used as note / callout backgrounds."""
    rects = []
    for r in page.rects or []:
        fill = r.get("non_stroking_color")
        w = float(r.get("width") or 0)
        h = float(r.get("height") or 0)
        if w < 80 or h < 20:
            continue
        # skip almost-full-page white / near-white
        if fill in (1, 0, (1, 1, 1), (0, 0, 0), None):
            # still accept if it's clearly a mid-page box with a non-white fill later
            continue
        # normalize 0-1 RGB
        if isinstance(fill, (list, tuple)) and len(fill) >= 3:
            rgb = tuple(round(float(c), 3) for c in fill[:3])
            # light blue / light grey callouts
            is_tint = (
                rgb[2] >= 0.85 and rgb[0] >= 0.8 and rgb[1] >= 0.8 and rgb != (1.0, 1.0, 1.0)
            ) or rgb in CALLOUT_COLORS
            if not is_tint:
                continue
        top = float(page.height) - float(r["y1"])
        bottom = float(page.height) - float(r["y0"])
        # skip header/footer bars
        if bottom < 55 or top > 775:
            continue
        rects.append((float(r["x0"]), top, float(r["x1"]), bottom))
    # keep only reasonably unique outer boxes (drop the per-line inner fills)
    rects.sort(key=lambda b: (b[1], -(b[3] - b[1])))
    merged: list[tuple] = []
    for box in rects:
        if any(
            abs(box[0] - m[0]) < 8
            and abs(box[2] - m[2]) < 8
            and box[1] >= m[1] - 2
            and box[3] <= m[3] + 2
            and (m[3] - m[1]) > (box[3] - box[1]) + 10
            for m in merged
        ):
            continue
        merged.append(box)
    return merged


def _extract_clean_table(page) -> list[Block]:
    """Try to recover real (multi-column) tables. Callout boxes are ignored."""
    blocks: list[Block] = []
    try:
        tables = page.find_tables() or []
    except Exception:
        return blocks
    page_no = page.page_number
    for t in tables:
        raw = t.extract() or []
        if not raw:
            continue
        # drop fully empty rows
        rows = [[(c or "").replace("\n", " ").strip() for c in row] for row in raw]
        rows = [r for r in rows if any(r)]
        if not rows:
            continue
        ncols = max(len(r) for r in rows)
        # count rows that have 2+ non-empty cells
        multi = sum(1 for r in rows if sum(1 for c in r if c) >= 2)
        if ncols < 2 or multi < 2:
            continue
        # reject garbage tables (too many empty cells, words split across columns)
        filled = sum(1 for r in rows for c in r if c)
        total = sum(len(r) for r in rows) or 1
        if filled / total < 0.35:
            continue
        # normalize row length
        rows = [r + [""] * (ncols - len(r)) for r in rows]
        header = rows[0]
        # if the first row is weak, still use it
        md = [_markdown_row(header), "|" + "|".join("---" for _ in header) + "|"]
        for r in rows[1:]:
            md.append(_markdown_row(r))
        markdown = "\n".join(md)
        x0, y0, x1, y1 = t.bbox
        top = float(page.height) - float(y1)
        bottom = float(page.height) - float(y0)
        blocks.append(
            Block(
                typ="table",
                text=markdown,
                page=page_no,
                bbox=(float(x0), top, float(x1), bottom),
                table_markdown=markdown,
            )
        )
    return blocks


def _markdown_row(cells: list[str]) -> str:
    cleaned = [c.replace("|", "\\|") for c in cells]
    return "| " + " | ".join(cleaned) + " |"


def _starts_lower(text: str) -> bool:
    return bool(re.match(r"^[a-zа-яё(]", text or ""))


def _looks_unfinished(text: str) -> bool:
    t = (text or "").rstrip()
    return not re.search(r"[.!?…:]$", t)


def _merge_paragraphs(lines: list[dict]) -> list[dict]:
    """Merge wrapped lines of the same paragraph / list item."""
    if not lines:
        return []
    merged = [dict(lines[0], typ=lines[0]["typ"])]
    for line in lines[1:]:
        prev = merged[-1]
        typ = line["typ"]
        if typ in {"heading", "title", "heading_cont"}:
            if typ == "heading_cont" and prev["typ"] in {"heading", "heading_cont", "title"}:
                prev["text"] = normalize_spaces(prev["text"] + " " + line["text"])
                prev["bottom"] = line["bottom"]
                prev["x1"] = max(prev["x1"], line["x1"])
                continue
            merged.append(dict(line, typ="heading" if typ == "heading_cont" else typ))
            continue
        gap = line["top"] - prev["bottom"]
        close = 0 <= gap <= max(prev.get("size") or 10, line.get("size") or 10) * 1.5
        # wrapped continuation of a list item (the overflow line is a paragraph)
        if (
            prev["typ"] == "list_item"
            and typ in {"paragraph", "note"}
            and close
            and line["x0"] >= prev["x0"] - 8
            and not LIST_START_RE.match(line["text"])
        ):
            prev["text"] = normalize_spaces(prev["text"] + " " + line["text"])
            prev["bottom"] = line["bottom"]
            prev["x1"] = max(prev["x1"], line["x1"])
            continue
        if typ == "list_item":
            merged.append(dict(line))
            continue
        same_type = prev["typ"] in {"paragraph", "note"} and typ == prev["typ"]
        indent_ok = abs(line["x0"] - prev["x0"]) <= 18
        if same_type and indent_ok and close and not LIST_START_RE.match(line["text"]):
            # definition-list / new sentence starting with a capital: keep a newline
            # so "Тип – ...\nМодель – ..." stays readable
            looks_like_field = " – " in (line["text"] or "") or " – " in (prev["text"] or "")
            use_newline = (not _starts_lower(line["text"])) and (
                (not _looks_unfinished(prev["text"])) or looks_like_field
            )
            if use_newline or looks_like_field:
                # start a new block (cleaner for field lists)
                merged.append(dict(line))
                continue
            prev["text"] = normalize_spaces(prev["text"] + " " + line["text"])
            prev["bottom"] = line["bottom"]
            prev["x1"] = max(prev["x1"], line["x1"])
            continue
        merged.append(dict(line))
    return merged


def _page_words(page) -> list[dict]:
    words = page.extract_words(
        x_tolerance=3,
        y_tolerance=3,
        keep_blank_chars=False,
        extra_attrs=["fontname", "size"],
        use_text_flow=False,
    ) or []
    kept = []
    for w in words:
        if is_in_header_footer_band(float(w["top"]), page.height):
            continue
        if is_noise_text(w["text"], allow_bare_numbers=True):
            continue
        kept.append(w)
    return kept


def _extract_title_from_cover(pdf) -> str:
    page = pdf.pages[0]
    words = page.extract_words(extra_attrs=["fontname", "size"]) or []
    lines = _group_lines(words, y_tol=4)
    title_parts = []
    for line in lines:
        if is_noise_text(line["text"]) or is_in_header_footer_band(line["top"], page.height):
            continue
        if _is_bold(line["fontname"]) and line["size"] >= 16:
            title_parts.append(line["text"])
    title = normalize_spaces(" ".join(title_parts))
    return title



def _merge_across_pages(blocks: list[Block]) -> list[Block]:
    """Glue a sentence / callout that was split by a page break."""
    if not blocks:
        return blocks
    out = [blocks[0]]
    for b in blocks[1:]:
        prev = out[-1]
        if b.typ == "image" or prev.typ == "image" or b.typ == "heading" or prev.typ == "heading":
            out.append(b)
            continue
        if b.page != prev.page + 1:
            out.append(b)
            continue
        # previous block ends near the bottom, new one starts near the top
        prev_bottom = prev.bbox[3] if prev.bbox else 0
        new_top = b.bbox[1] if b.bbox else 0
        if prev_bottom < 620 or new_top > 160:
            out.append(b)
            continue
        if LIST_START_RE.match(b.text or "") and not _starts_lower(b.text or ""):
            # a genuine new step, not a wrapped line (wrapped already lost its number)
            if re.match(r"^\d+[.)]", b.text or "") or re.match(r"^[•●○▪]", b.text or ""):
                out.append(b)
                continue
        if b.typ in {prev.typ, "paragraph", "note", "list_item"} and prev.typ in {"paragraph", "note", "list_item"}:
            joined = normalize_spaces((prev.text or "") + " " + (b.text or ""))
            bbox = None
            if prev.bbox and b.bbox:
                bbox = (
                    min(prev.bbox[0], b.bbox[0]),
                    prev.bbox[1],
                    max(prev.bbox[2], b.bbox[2]),
                    b.bbox[3],
                )
            out[-1] = replace(
                prev,
                text=joined,
                typ="note" if "note" in {prev.typ, b.typ} else prev.typ,
                bbox=bbox,
                meta={**prev.meta, "continued_on_page": b.page},
            )
            continue
        out.append(b)
    return out


def parse_pdf(
    path: str | Path,
    images_dir: str | Path | None = None,
    doc_title: str | None = None,
) -> list[Block]:
    """Parse a Confluence/Word-exported PDF into an ordered list of Blocks.

    Images are extracted (no vision / no OCR) and inserted in reading order
    as typ='image' blocks, later turned into image_placeholder chunks.
    """
    path = Path(path)
    with pdfplumber.open(str(path)) as pdf:
        cover_title = doc_title or _extract_title_from_cover(pdf) or path.stem
        short = short_doc_title(cover_title)
        slug = _doc_slug(cover_title, short)

        # TOC lives on early pages titled "Table of Contents"
        toc_text_parts: list[str] = []
        toc_page_numbers: set[int] = set()
        for i, page in enumerate(pdf.pages[:4]):
            raw = page.extract_text() or ""
            if re.search(r"Table of Contents", raw, re.I) or raw.count("....") >= 8:
                toc_text_parts.append(raw)
                toc_page_numbers.add(i + 1)
        toc = parse_toc_text("\n".join(toc_text_parts))

        blocks: list[Block] = []
        # document title as a leading title block (not chunked as body)
        blocks.append(
            Block(
                typ="title",
                text=cover_title,
                page=1,
                font_size=24,
                font_name="Arial-BoldMT",
                meta={"short_title": short, "slug": slug, "toc": [e.__dict__ for e in toc]},
            )
        )

        for page in pdf.pages:
            page_no = page.page_number
            # skip official TOC pages (dotted-leader pages), but keep later
            # "1 Содержание" body sections — they may contain unique notes
            if page_no in toc_page_numbers:
                continue

            words = _page_words(page)
            lines = _group_lines(words)
            # drop residual TOC-leader lines that slipped onto a body page
            lines = [ln for ln in lines if not is_toc_leader_line(ln["text"]) and not is_noise_text(ln["text"])]

            callouts = _collect_callout_rects(page)
            annotated: list[dict] = []
            last_heading_line = None
            for ln in lines:
                typ = _line_to_type(ln, toc, last_heading_line)
                rec = dict(ln, typ=typ)
                if typ in {"heading", "heading_cont"}:
                    last_heading_line = rec
                elif typ == "title" and last_heading_line is None and ln["size"] >= 20:
                    last_heading_line = rec
                if typ in {"paragraph", "list_item"} and _is_callout_line(ln, callouts):
                    rec["typ"] = "note" if typ == "paragraph" else typ
                    rec["in_callout"] = True
                annotated.append(rec)

            merged = _merge_paragraphs(annotated)
            for rec in merged:
                typ = rec["typ"]
                if typ == "heading_cont":
                    typ = "heading"
                level = None
                number = title = None
                if typ == "heading":
                    entry = match_toc_entry(rec["text"], toc)
                    if entry:
                        number, title, level = entry.number, entry.title, entry.level
                    else:
                        m = NUMBERED_HEADING_RE.match(rec["text"])
                        if m:
                            number = m.group("num")
                            title = normalize_spaces(m.group("title"))
                            level = number.count(".") + 1
                blocks.append(
                    Block(
                        typ=typ if typ != "heading_cont" else "heading",
                        text=rec["text"],
                        page=page_no,
                        bbox=(rec["x0"], rec["top"], rec["x1"], rec["bottom"]),
                        font_size=rec["size"],
                        font_name=rec["fontname"],
                        heading_level=level,
                        section_number=number,
                        section_title=title,
                        meta={"in_callout": bool(rec.get("in_callout")), "x0": rec["x0"]},
                    )
                )

            for tb in _extract_clean_table(page):
                # only keep if we actually produced markdown with several columns
                blocks.append(tb)

        # images
        if images_dir is not None:
            image_blocks = extract_pdf_images(path, images_dir, slug)
            blocks.extend(image_blocks)

        # reading order: title first, then (page, y, x), images included
        title_blocks = [b for b in blocks if b.typ == "title"]
        rest = [b for b in blocks if b.typ != "title"]

        def sort_key(b: Block):
            y = b.bbox[1] if b.bbox else 0
            x = b.bbox[0] if b.bbox else 0
            # images slightly after text at the same vertical position (captions often sit above)
            typ_rank = 1 if b.typ == "image" else 0
            return (b.page, y, typ_rank, x)

        rest.sort(key=sort_key)
        rest = _merge_across_pages(rest)
        return title_blocks + rest
