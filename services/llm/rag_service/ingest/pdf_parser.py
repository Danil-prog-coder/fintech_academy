"""PDF parser (FR-ING-02): pdfplumber/pypdf based layout parser from bars_chunker -> unified Blocks."""

from __future__ import annotations

import re
from pathlib import Path

from .blocks import Block, ParsedDocument
from .pdf_legacy.pdf_parse import parse_pdf as _legacy_parse_pdf
from .util import slugify

_LIST_RE = re.compile(r"^(?P<m>[•●○▪►‣·]|[-–—]|\d{1,2}[.)]|[a-zа-я][.)]|[ivx]{1,4}[.)])\s+(?P<t>.*)$", re.S)


def parse_pdf(path: str | Path, images_dir: str | Path) -> ParsedDocument:
    path = Path(path)
    legacy = _legacy_parse_pdf(path, images_dir=Path(images_dir))
    title_block = next((b for b in legacy if b.typ == "title"), None)
    title = (title_block.meta.get("short_title") if title_block else None) or path.stem
    full_title = title_block.text if title_block else title
    blocks: list[Block] = []
    for b in legacy:
        if b.typ == "title":
            continue
        x0 = (b.bbox[0] if b.bbox else 70) or 70
        nested = 4 if x0 > 95 else 0
        if b.typ == "heading":
            level = (b.heading_level or 1) + 1
            txt = f"{b.section_number} {b.section_title}" if b.section_number and b.section_title else b.text
            blocks.append(Block("heading", txt, level=level, page=b.page))
        elif b.typ == "table":
            rows = []
            for line in (b.table_markdown or "").splitlines():
                if re.match(r"^\s*\|?\s*-{3,}", line):
                    continue
                rows.append([c.strip() for c in line.strip().strip("|").split("|")])
            blocks.append(Block("table", rows=rows, page=b.page, indent=nested))
        elif b.typ == "image":
            blocks.append(Block("image", image_path=str((Path(images_dir) / Path(b.image_ref).name).resolve()) if b.image_ref else None, alt="Изображение", page=b.page, indent=nested))
        elif b.typ == "note":
            blocks.append(Block("callout", b.text, page=b.page, indent=nested))
        elif b.typ == "list_item":
            m = _LIST_RE.match(b.text)
            marker = m.group("m") if m else "-"
            if marker in "•●○▪►‣·–—":
                marker = "-"
            blocks.append(Block("list_item", m.group("t") if m else b.text, marker=marker, page=b.page, indent=nested))
        elif b.typ == "caption":
            blocks.append(Block("paragraph", b.text, page=b.page, indent=nested))
        else:
            blocks.append(Block("paragraph", b.text, page=b.page, indent=nested))
    return ParsedDocument(title=title, doc_id=slugify(title), source_file=path.name, blocks=blocks, meta={"full_title": full_title})
