"""Markdown / plain-text parser -> Blocks (FR-ING-02). Also used for Git-hosted docs (RK-7)."""

from __future__ import annotations

import re
from pathlib import Path

from .blocks import Block, ParsedDocument
from .util import slugify

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
IMAGE_RE = re.compile(r"^\s*!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)(?:\s+\"[^\"]*\")?\)\s*$")
LIST_RE = re.compile(r"^(?P<ind>\s*)(?P<marker>[-*+•]|\d{1,3}[.)]|[a-zа-я][.)]|[ivxlc]{1,5}[.)])\s+(?P<text>.*)$")
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
QUOTE_RE = re.compile(r"^(?P<ind>\s*)>\s?(?P<text>.*)$")
TOC_LINK_RE = re.compile(r"^\s*\[[^\]]+\]\(#[^)]*\)\s*$")
FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _indent_width(s: str) -> int:
    return len(s.expandtabs(4)) - len(s.expandtabs(4).lstrip(" "))


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def parse_markdown_text(text: str, base_dir: Path, *, title: str | None = None, source_file: str = "") -> ParsedDocument:
    meta: dict = {}
    fm = FRONT_MATTER_RE.match(text)
    if fm:  # FR-GIT-04: YAML front matter as metadata (simple key: value)
        for line in fm.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip("\"'")
        text = text[fm.end():]
    lines = text.splitlines()
    blocks: list[Block] = []
    doc_title = title or meta.get("title")
    i = 0
    para: list[str] = []
    para_indent = 0

    def flush_para() -> None:
        nonlocal para
        if para:
            blocks.append(Block("paragraph", " ".join(s.strip() for s in para).strip(), indent=para_indent))
            para = []

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush_para()
            i += 1
            continue
        m = HEADING_RE.match(line)
        if m and _indent_width(line) < 4:
            flush_para()
            level = len(m.group(1))
            htext = m.group(2).strip()
            if level == 1 and doc_title is None:
                doc_title = htext
            if re.fullmatch(r"(Содержание|Оглавление|Table of Contents)", htext, re.I):
                i += 1  # duplicated TOC heading (unnumbered); its link list is dropped below
                continue
            blocks.append(Block("heading", htext, level=level))
            i += 1
            continue
        m = IMAGE_RE.match(line)
        if m:
            flush_para()
            src = m.group("src")
            path = (base_dir / src).resolve() if not src.startswith(("http://", "https://")) else None
            blocks.append(Block("image", alt=m.group("alt"), image_path=str(path) if path else src, indent=_indent_width(line)))
            i += 1
            continue
        if TABLE_RE.match(line):
            flush_para()
            ind = _indent_width(line)
            rows: list[list[str]] = []
            while i < len(lines) and TABLE_RE.match(lines[i]):
                if not TABLE_SEP_RE.match(lines[i]):
                    rows.append(_split_row(lines[i]))
                i += 1
            blocks.append(Block("table", rows=rows, indent=ind))
            continue
        m = QUOTE_RE.match(line)
        if m:
            flush_para()
            ind = _indent_width(m.group("ind"))
            qlines: list[str] = []
            while i < len(lines):
                mq = QUOTE_RE.match(lines[i])
                if not mq:
                    break
                qlines.append(mq.group("text"))
                i += 1
            qtext = "\n".join(qlines).strip()
            qtext = re.sub(r"\n{2,}", "\n", qtext)
            blocks.append(Block("callout", qtext, indent=ind))
            continue
        m = LIST_RE.match(line)
        if m:
            flush_para()
            ind = _indent_width(m.group("ind"))
            item = [m.group("text")]
            i += 1
            # lazy continuation lines (more indented, not a new construct)
            while i < len(lines) and lines[i].strip() and not (
                LIST_RE.match(lines[i]) or HEADING_RE.match(lines[i]) or IMAGE_RE.match(lines[i])
                or TABLE_RE.match(lines[i]) or QUOTE_RE.match(lines[i])
            ) and _indent_width(lines[i]) > ind:
                item.append(lines[i].strip())
                i += 1
            blocks.append(Block("list_item", " ".join(item).strip(), marker=m.group("marker"), indent=ind))
            continue
        if not para:
            para_indent = _indent_width(line)
        para.append(line)
        i += 1
    flush_para()

    # drop link-only TOC lists ("## Содержание" with [x](#anchor) items) — duplicated TOC (FR-ING-03)
    blocks = [b for b in blocks if not (b.kind == "list_item" and TOC_LINK_RE.match(b.text))]
    doc_title = doc_title or Path(source_file).stem
    return ParsedDocument(
        title=doc_title,
        doc_id=slugify(Path(source_file).stem or doc_title),
        source_file=source_file,
        source_type=meta.get("source_type") or "upload",
        blocks=blocks,
        meta=meta,
    )


def parse_markdown(path: str | Path) -> ParsedDocument:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".txt":
        return parse_text(text, source_file=path.name)
    return parse_markdown_text(text, path.parent, source_file=path.name)


def parse_text(text: str, source_file: str) -> ParsedDocument:
    """Plain text: numbered lines like '2.1 Title' become headings; the rest is paragraphs."""
    md_lines = []
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+(?:\.\d+){0,3})\.?\s+([А-ЯЁA-Z].{0,80})$", line)
        if m and not line.rstrip().endswith((".", ",", ";", ":")):
            level = m.group(1).count(".") + 2
            md_lines.append("#" * min(level, 6) + f" {m.group(1)} {m.group(2).strip()}")
        else:
            md_lines.append(line)
    return parse_markdown_text("\n".join(md_lines), Path("."), source_file=source_file)
