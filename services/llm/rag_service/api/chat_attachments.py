"""Extract bounded text from the files attached to a single question."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable, Iterator
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pydantic import BaseModel, Field
from pypdf import PdfReader

from ..agent.input_guard import sanitize_untrusted

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 8_000
MAX_PDF_PAGES = 50
MAX_DOCX_UNCOMPRESSED = 25 * 1024 * 1024


class AttachmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    data_base64: str = Field(min_length=1, max_length=7_000_000)


class AttachmentRejected(ValueError):
    pass


def _docx_text(data: bytes) -> Iterator[str]:
    with ZipFile(BytesIO(data)) as archive:
        if sum(entry.file_size for entry in archive.infolist()) > MAX_DOCX_UNCOMPRESSED:
            raise ValueError("DOCX expands beyond the limit")
    document = Document(BytesIO(data))
    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            yield block.text
        elif isinstance(block, Table):
            for row in block.rows:
                yield " | ".join(cell.text for cell in row.cells)


def _pdf_text(data: bytes) -> Iterator[str]:
    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("encrypted PDF")
    has_text = False
    for page in reader.pages[:MAX_PDF_PAGES]:
        text = (page.extract_text() or "").strip()
        if text:
            has_text = True
            yield text
    if has_text and len(reader.pages) > MAX_PDF_PAGES:
        yield "[остальные страницы пропущены]"


def _excerpt(parts: Iterable[str]) -> str:
    remaining = MAX_TEXT
    lines = []
    for part in parts:
        text = part.strip()
        if not text:
            continue
        if len(text) > remaining:
            lines.append(text[:remaining] + "… [текст сокращён]")
            break
        lines.append(text)
        remaining -= len(text) + 1
        if remaining <= 0:
            lines.append("[текст сокращён]")
            break
    return "\n".join(lines)


def extract_attachment_context(attachments: list[AttachmentIn]) -> str:
    documents = []
    for attachment in attachments:
        name = PurePosixPath(attachment.name.replace("\\", "/")).name
        suffix = PurePosixPath(name).suffix.lower()
        try:
            data = base64.b64decode(attachment.data_base64, validate=True)
            if not 0 < len(data) <= MAX_BYTES:
                raise ValueError("attachment size out of bounds")
            if suffix == ".pdf":
                text = _excerpt(_pdf_text(data))
            elif suffix == ".docx":
                text = _excerpt(_docx_text(data))
            elif suffix in {".txt", ".md", ".csv"}:
                encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
                text = _excerpt([data.decode(encoding)])
                if "\0" in text:
                    raise ValueError("binary content")
            else:
                raise ValueError("unsupported type")
        except Exception as e:
            raise AttachmentRejected(f"Не удалось прочитать файл «{name}». Проверьте формат и размер файла.") from e
        if not text:
            hint = " Скан можно приложить как изображение." if suffix == ".pdf" else ""
            raise AttachmentRejected(f"В файле «{name}» не найден текст.{hint}")
        documents.append({"name": sanitize_untrusted(name)[0], "text": sanitize_untrusted(text)[0]})
    return json.dumps(documents, ensure_ascii=False)
