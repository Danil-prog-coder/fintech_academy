"""Shared intermediate representations.

Both parse_pdf() and parse_docx() produce a list of Block objects.
The chunker then turns those blocks into Chunk objects written to JSONL.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

BlockType = Literal[
    "heading",
    "paragraph",
    "list_item",
    "table",
    "note",
    "image",
    "caption",
    "title",
]

ChunkType = Literal["text", "table", "list", "image_placeholder", "mixed"]


@dataclass
class TocEntry:
    number: str
    title: str
    level: int
    page: int | None = None


@dataclass
class Block:
    typ: BlockType
    text: str
    page: int
    bbox: tuple[float, float, float, float] | None = None  # x0, top, x1, bottom
    font_size: float | None = None
    font_name: str | None = None
    heading_level: int | None = None
    section_number: str | None = None
    section_title: str | None = None
    image_ref: str | None = None
    table_markdown: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def with_section(self, number: str | None, title: str | None) -> "Block":
        return replace(self, section_number=number, section_title=title)


@dataclass
class Chunk:
    chunk_id: str
    doc_title: str
    doc_short_title: str
    section_number: str
    section_title: str
    section_path: str
    pages: list[int]
    chunk_type: ChunkType
    text: str
    text_for_embedding: str
    image_refs: list[str] = field(default_factory=list)
    token_estimate: int = 0
    source_file: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d
