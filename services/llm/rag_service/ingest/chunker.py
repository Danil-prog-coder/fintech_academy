"""Structural chunking (FR-RET-01/02, FR-ING-05).

Blocks -> sections (by heading tree) -> units (a top-level paragraph / list item with all nested
content, a callout, ...) -> packed chunks. Tables and images become separate chunks of type
`table` / `image`; text chunks keep a short marker in their place so the agent can still see them.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable

import tiktoken

from .blocks import Block, ParsedDocument
from .noise import clean_text, is_empty_step

log = logging.getLogger(__name__)


def _load_encoding():
    """cl100k_base is downloaded on first use; the Docker image bakes it in (TIKTOKEN_CACHE_DIR).

    Without network and without the cached file the chunker must still work: token counts fall back to
    ~4 characters per token, which is what cl100k_base gives on Russian prose within ±20%.
    """
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception as e:  # noqa: BLE001  (network / proxy / missing cache)
        log.warning("tiktoken encoding unavailable (%s): approximate token counts", str(e)[:120])
        return None


_ENC = _load_encoding()
SECTION_NUM_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\.?\s+(?P<title>.+)$")
NUMBERED_MARKER_RE = re.compile(r"^\d+[.)]$")


def ntokens(text: str) -> int:
    if _ENC is None:
        return max(1, (len(text) + 3) // 4) if text else 0
    return len(_ENC.encode(text))


@dataclass
class ImageInfo:
    image_id: str
    path: str
    kind: str = "screenshot"  # screenshot | annotated_screenshot | button_panel | bpmn | photo | icon | video_thumbnail | broken | other
    title: str = ""
    description: str = ""
    ocr_text: str = ""
    broken: bool = False
    crop_path: str = ""  # FR-ING-06: cut-out of the element in a red frame (if any)
    model: str = ""  # the model that wrote the description (empty: not described; "ocr": OCR only)
    ocr_lines: str = ""  # verbatim text read by classic OCR (VISION_MODE=vlm+ocr | ocr), lines joined by « | »


@dataclass
class Chunk:
    chunk_id: str  # stable within a document version: f"{doc_id}:{order:04d}"
    doc_id: str
    document_title: str
    section_path: list[str]
    section_number: str | None
    chunk_type: str  # text | table | image | callout
    text: str  # what the agent sees / what quotes must come from
    order: int
    step_label: str | None = None
    image_ids: list[str] = field(default_factory=list)
    page: int | None = None
    source_file: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def section_path_str(self) -> str:
        return " → ".join([self.document_title, *self.section_path] + ([self.step_label] if self.step_label else []))

    def embedding_text(self) -> str:
        # FR-RET-02: contextual header before the body
        return f"{self.section_path_str}\n{self.text}"


@dataclass
class Section:
    path: list[str]
    number: str | None
    blocks: list[Block]


def split_sections(doc: ParsedDocument) -> list[Section]:
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    current = Section(path=[], number=None, blocks=[])
    for b in doc.blocks:
        if b.kind == "heading":
            if b.level == 1 and b.text.strip() == doc.title.strip():
                continue
            if current.blocks:
                sections.append(current)
            while stack and stack[-1][0] >= b.level:
                stack.pop()
            stack.append((b.level, b.text.strip()))
            m = SECTION_NUM_RE.match(b.text.strip())
            num = m.group("num") if m and "." in m.group("num") or (m and len(m.group("num")) <= 2) else None
            current = Section(path=[t for _, t in stack], number=num, blocks=[])
        else:
            current.blocks.append(b)
    if current.blocks:
        sections.append(current)
    return sections


def _units(blocks: list[Block]) -> list[list[Block]]:
    """Group a section's blocks into atomic units: a top-level item + everything nested under it."""
    units: list[list[Block]] = []
    for b in blocks:
        top_level = b.indent == 0 and b.kind != "image"
        if not units:
            units.append([b])
        elif top_level:
            units.append([b])
        else:
            units[-1].append(b)  # nested content or an image belonging to the previous item
    return units


def _step_label(unit: list[Block]) -> str | None:
    first = unit[0]
    if first.kind == "list_item" and first.marker and NUMBERED_MARKER_RE.match(first.marker):
        words = re.sub(r"[*`«»\"]", "", first.text).split()
        short = " ".join(words[:5]) + ("…" if len(words) > 5 else "")
        return f"п. {first.marker.rstrip('.)')} «{short}»"
    return None


class _Renderer:
    def __init__(self, images: dict[str, ImageInfo], image_id_for: Callable[[str], str]):
        self.images = images
        self.image_id_for = image_id_for

    def render(self, blocks: list[Block], base_indent: int = 0) -> tuple[str, list[str]]:
        lines: list[str] = []
        image_ids: list[str] = []
        for b in blocks:
            pad = " " * max(0, b.indent - base_indent)
            if b.kind == "paragraph":
                lines.append(pad + b.text)
            elif b.kind == "list_item":
                lines.append(f"{pad}{b.marker or '-'} {b.text}")
            elif b.kind == "callout":
                lines.extend(pad + "> " + ln for ln in b.text.splitlines())
            elif b.kind == "table":
                cap = b.meta.get("caption") or "таблица"
                lines.append(f"{pad}[Таблица: {cap} — см. отдельный фрагмент типа table]")
            elif b.kind == "image":
                iid = self.image_id_for(b.image_path or "")
                info = self.images.get(iid)
                if info and info.broken:
                    lines.append(f"{pad}[изображение не сохранилось при экспорте]")
                    continue
                title = (info.title if info and info.title else b.alt) or "изображение"
                lines.append(f"{pad}[Изображение {iid}: {title}]")
                image_ids.append(iid)
        return "\n".join(lines), image_ids


def _table_markdown(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    header = "| " + " | ".join(norm[0]) + " |"
    sep = "| " + " | ".join(["---"] * width) + " |"
    body = ["| " + " | ".join(r) + " |" for r in norm[1:]]
    return [header, sep, *body]


def chunk_document(
    doc: ParsedDocument,
    images: dict[str, ImageInfo],
    image_id_for: Callable[[str], str],
    *,
    max_tokens: int = 650,
    target_tokens: int = 420,
    table_max_tokens: int = 500,
    warnings: list[str] | None = None,
) -> list[Chunk]:
    warnings = warnings if warnings is not None else doc.warnings
    renderer = _Renderer(images, image_id_for)
    chunks: list[Chunk] = []
    order = 0

    def emit(section: Section, ctype: str, text: str, step: str | None, image_ids: list[str], page=None, meta=None):
        nonlocal order
        text = text.strip()
        if not text:
            return
        chunks.append(Chunk(
            chunk_id=f"{doc.doc_id}:{order:04d}", doc_id=doc.doc_id, document_title=doc.title,
            section_path=section.path, section_number=section.number, chunk_type=ctype, text=text,
            order=order, step_label=step, image_ids=list(dict.fromkeys(image_ids)), page=page,
            source_file=doc.source_file, meta=meta or {},
        ))
        order += 1

    for section in split_sections(doc):
        where = " → ".join([doc.title, *section.path])
        # cleaning (FR-ING-03/07) on text blocks
        for b in section.blocks:
            if b.kind in ("paragraph", "list_item", "callout"):
                b.text = clean_text(b.text, warnings, where)
                if b.kind == "list_item" and is_empty_step(b.text):
                    warnings.append(f"empty_step: '{b.marker}' {where}")
                    b.text = "[содержимое шага не сохранилось при экспорте]"
        # table captions: preceding paragraph
        for i, b in enumerate(section.blocks):
            if b.kind == "table":
                prev = next((p for p in reversed(section.blocks[:i]) if p.kind in ("paragraph", "callout", "list_item")), None)
                cap = prev.text.split(".")[0][:140] if prev else ""
                b.meta["caption"] = cap or "таблица"

        units = _units(section.blocks)
        pending: list[tuple[str, list[str], str | None, str]] = []  # (text, image_ids, step_label, unit_type)

        def flush_pending():
            if not pending:
                return
            text = "\n".join(p[0] for p in pending)
            ids = [i for p in pending for i in p[1]]
            steps = [p[2] for p in pending if p[2]]
            if len(steps) > 1:
                n1 = steps[0].split("«")[0].strip()
                n2 = steps[-1].split("«")[0].strip().replace("п. ", "")
                step = f"{n1}–{n2}"
            else:
                step = steps[0] if steps else None
            ctype = "callout" if all(p[3] == "callout" for p in pending) else "text"
            emit(section, ctype, text, step, ids)
            pending.clear()

        for unit in units:
            ulabel = _step_label(unit)
            for b in unit:
                b.meta["step"] = ulabel
            text, ids = renderer.render(unit)
            if not text.strip():
                continue
            label = _step_label(unit)
            utype = "callout" if all(b.kind in ("callout", "image") for b in unit) and any(b.kind == "callout" for b in unit) else "text"
            size = ntokens(text)
            if size > max_tokens:
                flush_pending()
                _emit_split_unit(unit, label, renderer, section, emit, max_tokens, target_tokens)
                continue
            cur = ntokens("\n".join(p[0] for p in pending)) if pending else 0
            if pending and cur + size > target_tokens:
                flush_pending()
            pending.append((text, ids, label, utype))
        flush_pending()

        # separate table chunks (FR-ING-05): header repeated in every piece
        for b in section.blocks:
            if b.kind != "table" or not b.rows:
                continue
            md = _table_markdown(b.rows)
            head, rows = md[:2], md[2:]
            cap = b.meta.get("caption", "таблица")
            piece: list[str] = []
            for r in rows:
                if piece and ntokens("\n".join([cap, *head, *piece, r])) > table_max_tokens:
                    emit(section, "table", "\n".join([cap, *head, *piece]), b.meta.get("step"), [], meta={"caption": cap})
                    piece = []
                piece.append(r)
            emit(section, "table", "\n".join([cap, *head, *piece]), b.meta.get("step"), [], meta={"caption": cap})

        # image chunks (FR-ING-04: description indexed as a separate chunk of type image)
        seen: set[str] = set()
        for idx, b in enumerate(section.blocks):
            if b.kind != "image":
                continue
            iid = image_id_for(b.image_path or "")
            if iid in seen:
                continue
            seen.add(iid)
            info = images.get(iid)
            if info and info.broken:
                continue
            context = _image_context(section.blocks, idx)
            parts = [f"Изображение ({info.kind if info else 'изображение'}): {(info.title if info and info.title else b.alt) or 'без подписи'}"]
            if context:
                parts.append(f"Текст рядом в документе: {context}")
            if info and info.description:
                parts.append(f"Описание изображения: {info.description}")
            if info and info.ocr_text:
                parts.append(f"Надписи на изображении: {info.ocr_text}")
            if info and info.ocr_lines:
                parts.append(f"Текст с изображения (OCR): {info.ocr_lines}")
            emit(section, "image", "\n".join(parts), b.meta.get("step"), [iid], meta={"image_kind": info.kind if info else None})
    return chunks


def _image_context(blocks: list[Block], idx: int, max_chars: int = 300) -> str:
    prev = [b.text for b in blocks[max(0, idx - 2):idx] if b.kind in ("paragraph", "list_item", "callout") and b.text]
    nxt = [b.text for b in blocks[idx + 1:idx + 2] if b.kind in ("paragraph", "list_item", "callout") and b.text]
    ctx = " … ".join(prev[-2:] + nxt)
    return ctx[:max_chars]


def _emit_split_unit(unit, label, renderer, section, emit, max_tokens, target_tokens):
    """Split an oversized unit by its first nested level; the head line is repeated in every part."""
    head = unit[0]
    rest = unit[1:]
    if not rest:
        text, ids = renderer.render(unit)
        _emit_by_lines(text, ids, label, section, emit, max_tokens)
        return
    child_indent = min(b.indent for b in rest if b.kind != "image") if any(b.kind != "image" for b in rest) else 0
    groups: list[list[Block]] = []
    for b in rest:
        if not groups or (b.indent <= child_indent and b.kind != "image"):
            groups.append([b])
        else:
            groups[-1].append(b)
    head_text, head_ids = renderer.render([head])
    buf: list[list[Block]] = []

    def names(gs):
        out = []
        for g in gs:
            m = re.match(r"\*\*(.+?)\*\*", g[0].text or "")
            if m:
                out.append(m.group(1))
        return out

    def flush():
        if not buf:
            return
        blocks = [b for g in buf for b in g]
        body, ids = renderer.render(blocks, base_indent=0)
        nm = names(buf)
        step = label or ""
        if nm:
            step = (step + " → " if step else "") + ", ".join(nm[:4]) + ("…" if len(nm) > 4 else "")
        text = head_text + "\n" + body
        if ntokens(text) > max_tokens * 1.6:
            _emit_by_lines(text, head_ids + ids, step or None, section, emit, max_tokens)
        else:
            emit(section, "text", text, step or None, head_ids + ids)
        buf.clear()

    for g in groups:
        gtext, _ = renderer.render(g)
        cur = ntokens("\n".join(renderer.render([b for gg in buf for b in gg])[0] for _ in [0])) if buf else 0
        if buf and cur + ntokens(gtext) > target_tokens:
            flush()
        buf.append(g)
    flush()


def _emit_by_lines(text, ids, label, section, emit, max_tokens):
    lines = text.splitlines()
    buf: list[str] = []
    for ln in lines:
        if buf and ntokens("\n".join(buf + [ln])) > max_tokens:
            emit(section, "text", "\n".join(buf), label, ids)
            buf = []
        buf.append(ln)
    if buf:
        emit(section, "text", "\n".join(buf), label, ids)
