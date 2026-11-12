"""Извлечение текста из файлов: текстовые форматы и код, PDF с текстовым слоем, DOCX.

Модуль не знает, откуда пришёл файл (вложение письма, загрузка документа, файл из
репозитория) и куда пойдёт текст: лимиты передаёт вызывающий код. Тип проверяется и по
расширению, и по содержимому. Ошибки парсеров не выходят наружу: у результата есть статус и
понятная пользователю причина. В логи пишется только тип ошибки, без содержимого.
"""

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from xml.etree import ElementTree

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 200_000  # по умолчанию с одного файла; дальше текст отрезается
PDF_MAX_PAGES = 300
DOCX_XML_MAX_BYTES = 40 * 1024 * 1024  # защита от zip-бомбы

TEXT_EXTENSIONS = {
    ".txt", ".text", ".md", ".markdown", ".rst", ".adoc", ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".xml", ".html", ".htm",
    ".log", ".sql", ".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".java", ".kt", ".go", ".rs",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".sh", ".ps1", ".bat", ".swift",
    ".scala", ".css", ".scss", ".vue", ".graphql", ".proto", ".tf", ".gradle",
}  # fmt: skip
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx"}

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_UNSAFE_NAME = re.compile(r'[\x00-\x1f\x7f"<>]')


class ExtractStatus(StrEnum):
    read = "read"  # текст извлечён
    unsupported = "unsupported"  # формат не поддерживается
    too_large = "too_large"
    empty = "empty"  # текста нет (например, скан без текстового слоя)
    unreadable = "unreadable"  # файл повреждён, зашифрован или не того типа


@dataclass
class Extracted:
    status: ExtractStatus
    text: str = ""
    truncated: bool = False
    message: str | None = None


def safe_name(filename: str) -> str:
    """Имя файла без пути, кавычек и угловых скобок: его можно класть в промпт и атрибуты."""
    name = PurePosixPath(filename.replace("\\", "/")).name
    return _UNSAFE_NAME.sub("_", name).strip()[:255] or "file"


def is_supported(filename: str) -> bool:
    return PurePosixPath(filename.lower()).suffix in SUPPORTED_EXTENSIONS


def _limit(text: str, max_chars: int) -> tuple[str, bool]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


def _decode_text(data: bytes) -> str | None:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if b"\x00" in data[:8192]:
        return None  # двоичный файл под текстовым расширением
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace")  # старые письма и выгрузки из Windows


def _extract_pdf(data: bytes, max_chars: int) -> Extracted:
    from pypdf import PdfReader  # тяжёлый импорт нужен только для PDF

    if b"%PDF-" not in data[:1024]:
        return Extracted(ExtractStatus.unreadable, message="Файл не похож на PDF.")
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")
        except Exception:  # noqa: BLE001 — неизвестные алгоритмы шифрования
            ok = 0
        if not ok:
            return Extracted(ExtractStatus.unreadable, message="PDF защищён паролем.")
    parts: list[str] = []
    size = 0
    truncated = len(reader.pages) > PDF_MAX_PAGES
    for page in reader.pages[:PDF_MAX_PAGES]:
        text = page.extract_text() or ""
        parts.append(text)
        size += len(text)
        if size > max_chars:
            truncated = True
            break
    text, cut = _limit("\n\n".join(parts), max_chars)
    return Extracted(ExtractStatus.read, text, truncated or cut)


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    out = []
    for node in paragraph.iter():
        if node.tag == _W + "t" and node.text:
            out.append(node.text)
        elif node.tag == _W + "tab":
            out.append("\t")
        elif node.tag in (_W + "br", _W + "cr"):
            out.append("\n")
    return "".join(out)


def _extract_docx(data: bytes, max_chars: int) -> Extracted:
    if not data.startswith(b"PK"):
        return Extracted(ExtractStatus.unreadable, message="Файл не похож на DOCX.")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        try:
            info = archive.getinfo("word/document.xml")
        except KeyError:
            return Extracted(ExtractStatus.unreadable, message="Файл не похож на DOCX.")
        # Размер из заголовка архива может врать, поэтому читаем с ограничением.
        with archive.open(info) as stream:
            xml = stream.read(DOCX_XML_MAX_BYTES + 1)
    if len(xml) > DOCX_XML_MAX_BYTES:
        return Extracted(ExtractStatus.too_large, message="Документ слишком большой.")
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        # В настоящем DOCX их не бывает; так отсекаем XML-бомбы и внешние сущности.
        return Extracted(ExtractStatus.unreadable, message="Документ повреждён.")
    root = ElementTree.fromstring(xml)
    body = root.find(_W + "body")
    paragraphs = [] if body is None else [_paragraph_text(p) for p in body.iter(_W + "p")]
    text, truncated = _limit("\n".join(paragraphs), max_chars)
    return Extracted(ExtractStatus.read, text, truncated)


def extract_text(
    filename: str, data: bytes, *, max_bytes: int, max_chars: int = MAX_TEXT_CHARS
) -> Extracted:
    """Текст файла или причина, по которой его не прочитать. Не бросает исключений."""
    suffix = PurePosixPath(filename.lower()).suffix
    if suffix not in SUPPORTED_EXTENSIONS:
        return Extracted(ExtractStatus.unsupported, message="Этот формат ИИ не читает.")
    if len(data) > max_bytes:
        return Extracted(ExtractStatus.too_large, message="Файл слишком большой для анализа.")
    try:
        if suffix == ".pdf":
            result = _extract_pdf(data, max_chars)
        elif suffix == ".docx":
            result = _extract_docx(data, max_chars)
        else:
            decoded = _decode_text(data)
            if decoded is None:
                return Extracted(ExtractStatus.unreadable, message="Файл не похож на текст.")
            text, truncated = _limit(decoded, max_chars)
            result = Extracted(ExtractStatus.read, text, truncated)
    except Exception as e:  # noqa: BLE001 — парсеры на чужих файлах падают как угодно
        log.warning("text extraction failed: %s", type(e).__name__)
        return Extracted(ExtractStatus.unreadable, message="Не удалось прочитать файл.")
    if result.status == ExtractStatus.read and not result.text.strip():
        message = "В PDF нет текстового слоя (скан?)." if suffix == ".pdf" else "Файл пустой."
        return Extracted(ExtractStatus.empty, message=message)
    return result
