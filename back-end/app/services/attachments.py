"""Вложения черновика как контекст для «Спросить у ИИ».

Пользователь прикладывает к письму файлы; их текст становится дополнительным контекстом для
ответа на вопросы черновика. Сам текст извлекает общий модуль `app.services.text_extract`,
здесь только почтовые лимиты, нарезка на фрагменты и выбор фрагментов под вопрос. Файлы, как и
сам черновик, нигде не сохраняются и в логи не попадают (FR-MAIL-05).

Длинные вложения режутся на фрагменты. Если весь текст влезает в лимит контекста, модель
получает его целиком, иначе к каждому вопросу подбираются самые близкие по смыслу фрагменты.
"""

import asyncio
import binascii
import math
from base64 import b64decode
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.core.errors import AppError
from app.llm.base import EmbeddingProvider
from app.services.indexer import EMBED_TEXT_CHARS, chunk_text
from app.services.text_extract import ExtractStatus, extract_text, safe_name

MAX_CHUNKS = 120  # фрагментов на все вложения запроса (столько уйдёт в эмбеддинги)

# Статус вложения в ответе API совпадает со статусом извлечения текста.
AttachmentStatus = ExtractStatus


@dataclass
class AttachmentChunk:
    order: int  # сквозной номер для восстановления порядка текста
    filename: str
    start_line: int
    end_line: int
    text: str
    vector: list[float] | None = None


@dataclass
class AttachmentReport:
    filename: str
    status: AttachmentStatus
    chars: int
    truncated: bool
    message: str | None


@dataclass
class AttachmentContext:
    reports: list[AttachmentReport] = field(default_factory=list)
    chunks: list[AttachmentChunk] = field(default_factory=list)

    @property
    def total_chars(self) -> int:
        return sum(len(c.text) for c in self.chunks)

    @property
    def names(self) -> list[str]:
        return list(dict.fromkeys(c.filename for c in self.chunks))


def decode_base64(content: str) -> bytes:
    try:
        return b64decode(content, validate=True)
    except (binascii.Error, ValueError):
        raise AppError("invalid_attachment", "Вложение не в формате base64.", 422) from None


async def prepare_attachments(
    files: list[tuple[str, str]], embeddings: EmbeddingProvider | None
) -> AttachmentContext:
    """files: пары (имя файла, содержимое в base64). Возвращает отчёт и фрагменты."""
    ctx = AttachmentContext()
    if not files:
        return ctx
    decoded = [(safe_name(name), decode_base64(content)) for name, content in files]
    settings = get_settings()
    if sum(len(data) for _, data in decoded) > settings.mail_ask_attachments_total_bytes:
        raise AppError("attachment_too_large", "Вложения слишком большие для анализа.", 413)

    max_bytes = settings.mail_ask_attachment_bytes
    extracted = await asyncio.to_thread(
        lambda: [extract_text(n, d, max_bytes=max_bytes) for n, d in decoded]
    )
    for (name, _), result in zip(decoded, extracted, strict=True):
        ctx.reports.append(
            AttachmentReport(
                filename=name,
                status=result.status,
                chars=len(result.text),
                truncated=result.truncated,
                message=result.message,
            )
        )
        if result.status != AttachmentStatus.read:
            continue
        for start, end, text in chunk_text(result.text, settings.index_chunk_chars):
            if len(ctx.chunks) >= MAX_CHUNKS:
                ctx.reports[-1].truncated = True
                break
            ctx.chunks.append(AttachmentChunk(len(ctx.chunks), name, start, end, text))

    # Эмбеддинги нужны, только если всё не влезает в контекст и придётся выбирать.
    if embeddings is not None and ctx.total_chars > settings.mail_ask_context_chars:
        vectors = await embeddings.embed(
            [f"{c.filename}\n{c.text}"[:EMBED_TEXT_CHARS] for c in ctx.chunks]
        )
        for chunk, vector in zip(ctx.chunks, vectors, strict=True):
            chunk.vector = vector
    return ctx


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def select_chunks(
    ctx: AttachmentContext | None, query_vectors: list[list[float]], budget: int
) -> list[AttachmentChunk]:
    """Фрагменты вложений для одного вопроса: все, если влезают, иначе самые близкие к нему."""
    if ctx is None or not ctx.chunks:
        return []
    if ctx.total_chars <= budget:
        return list(ctx.chunks)
    ranked = ctx.chunks
    if query_vectors and all(c.vector for c in ctx.chunks):
        ranked = sorted(
            ctx.chunks,
            key=lambda c: max(_cosine(c.vector, v) for v in query_vectors),
            reverse=True,
        )
    # Без векторов выбрать не по чему — тогда берётся начало документа.
    picked, used = [], 0
    for chunk in ranked:
        if used + len(chunk.text) <= budget:
            picked.append(chunk)
            used += len(chunk.text)
    return sorted(picked, key=lambda c: c.order)
