"""Unified intermediate representation produced by every parser (docx/pdf/md/txt)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

BlockKind = Literal["heading", "paragraph", "list_item", "table", "callout", "image"]


@dataclass
class Block:
    kind: BlockKind
    text: str = ""
    level: int = 0  # heading level (1..6); unused for other kinds
    indent: int = 0  # nesting depth inside a list item (0 = top level of the section)
    marker: str | None = None  # list marker: "4.", "a.", "-", "i."
    rows: list[list[str]] | None = None  # table rows, rows[0] = header
    image_path: str | None = None  # absolute path to the stored image file
    alt: str = ""
    page: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    title: str
    doc_id: str  # stable slug
    source_file: str
    source_type: str = "upload"  # upload | git (RK-7)
    blocks: list[Block] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
