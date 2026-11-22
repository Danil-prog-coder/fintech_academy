"""All required source formats go through one pipeline (FR-ING-01/02): .docx, .pdf, .md, .txt.

The documents are generated in the test, so the parsers are exercised on real files of each format,
not only on the Markdown copies of the knowledge base. No LLM, no embeddings.
"""

from pathlib import Path

import pytest
from docx import Document
from docx.shared import Inches
from PIL import Image, ImageDraw

from rag_service.ingest.crops import crop_red_frame, red_frame_bbox
from rag_service.ingest.pipeline import SUPPORTED, build_chunks, collect_files, parse_file

NOISE = 'Ошибка! Используйте вкладку "Главная" для применения Heading 1 к тексту, который должен здесь отображаться.'


def _screenshot(path: Path, frame: tuple[int, int, int, int] | None = (60, 40, 180, 90)) -> Path:
    im = Image.new("RGB", (400, 240), (245, 245, 245))
    d = ImageDraw.Draw(im)
    d.rectangle((10, 10, 390, 30), fill=(210, 220, 235))  # a toolbar
    d.text((70, 55), "Сохранить", fill=(20, 20, 20))
    if frame:
        d.rectangle(frame, outline=(230, 20, 20), width=3)
    im.save(path)
    return path


@pytest.fixture
def docx_file(tmp_path) -> Path:
    doc = Document()
    doc.core_properties.title = "Реестр оборудования"
    doc.add_paragraph(NOISE)
    doc.add_heading("1 Общие сведения", level=1)
    doc.add_paragraph("Документ предназначен для учёта оборудования.")
    doc.add_heading("1.1 Порядок работы", level=2)
    doc.add_paragraph("Открыть реестр", style="List Number")
    doc.add_paragraph("Нажать кнопку добавления", style="List Number")
    doc.add_paragraph("Заполнить поля", style="List Number 2")
    doc.add_paragraph("Сохранить запись", style="List Number")
    doc.add_paragraph().add_run().add_picture(str(_screenshot(tmp_path / "shot.png")), width=Inches(3))
    doc.add_heading("2 Статусы", level=1)
    t = doc.add_table(rows=3, cols=2)
    for r, (a, b) in enumerate([("Статус", "Значение"), ("Свободен", "можно выдать"), ("Списан", "выведен из учёта")]):
        t.cell(r, 0).text, t.cell(r, 1).text = a, b
    note = doc.add_table(rows=1, cols=1)
    note.cell(0, 0).text = "Важно: списанное оборудование не выдаётся."
    p = tmp_path / "reestr.docx"
    doc.save(p)
    return p


def test_docx_structure_tables_callouts_images_and_noise(docx_file, tmp_path):
    doc = parse_file(docx_file, tmp_path / "img")
    assert doc.title == "Реестр оборудования"
    assert [(b.level, b.text) for b in doc.blocks if b.kind == "heading"] == [
        (2, "1 Общие сведения"), (3, "1.1 Порядок работы"), (2, "2 Статусы")]
    items = [(b.marker, b.indent, b.text) for b in doc.blocks if b.kind == "list_item"]
    assert items == [("1.", 0, "Открыть реестр"), ("2.", 0, "Нажать кнопку добавления"), ("a.", 4, "Заполнить поля"), ("3.", 0, "Сохранить запись")]
    table = next(b for b in doc.blocks if b.kind == "table")
    assert table.rows == [["Статус", "Значение"], ["Свободен", "можно выдать"], ["Списан", "выведен из учёта"]]
    assert [b.text for b in doc.blocks if b.kind == "callout"] == ["Важно: списанное оборудование не выдаётся."]
    img = next(b for b in doc.blocks if b.kind == "image")
    assert Path(img.image_path).exists()
    assert not any("Ошибка!" in (b.text or "") for b in doc.blocks)  # export noise is dropped (FR-ING-03)


def test_docx_goes_through_chunking_with_image_fragments(docx_file, tmp_path, monkeypatch):
    from rag_service.config import get_settings

    monkeypatch.setattr(get_settings(), "state_dir", str(tmp_path / "var"))
    chunks, images, report = build_chunks([docx_file], describe=False)
    assert report["errors"] == [] and report["documents"][0]["tables"] == 1
    types = {c.chunk_type for c in chunks}
    assert {"text", "table", "image"} <= types
    assert any("Важно: списанное оборудование не выдаётся." in c.text for c in chunks)  # the note is kept
    steps = next(c for c in chunks if "Открыть реестр" in c.text)
    assert "Заполнить поля" in steps.text and steps.section_path[-1] == "1.1 Порядок работы"  # the list is not torn apart
    image_chunk = next(c for c in chunks if c.chunk_type == "image")
    # FR-ING-06: the element in the red frame is cut out and linked to the screenshot
    info = images[image_chunk.image_ids[0]]
    assert info.crop_path and Path(info.crop_path).exists()
    w, h = Image.open(info.crop_path).size
    assert w < 400 and h < 240


def test_red_frame_detection(tmp_path):
    framed = _screenshot(tmp_path / "a.png")
    x0, y0, x1, y1 = red_frame_bbox(framed)
    assert abs(x0 - 60) <= 4 and abs(y0 - 40) <= 4 and abs(x1 - 180) <= 5 and abs(y1 - 90) <= 5
    assert crop_red_frame(framed, tmp_path / "crop.png")
    w, h = Image.open(tmp_path / "crop.png").size
    assert 120 < w < 400 and 50 < h < 240  # the element with a margin, not the whole screenshot
    assert red_frame_bbox(_screenshot(tmp_path / "b.png", frame=None)) is None
    # a red line or a red-filled button is not a frame
    im = Image.new("RGB", (300, 200), "white")
    d = ImageDraw.Draw(im)
    d.line((20, 50, 250, 50), fill=(230, 20, 20), width=3)
    d.rectangle((40, 100, 200, 160), fill=(230, 20, 20))
    im.save(tmp_path / "c.png")
    assert red_frame_bbox(tmp_path / "c.png") is None
    # a narrow toolbar strip with one framed button (the shape of the panels in the real knowledge base)
    strip = Image.new("RGB", (338, 30), (240, 240, 240))
    ImageDraw.Draw(strip).rectangle((150, 3, 180, 26), outline=(230, 20, 20), width=2)
    strip.save(tmp_path / "strip.png")
    assert red_frame_bbox(tmp_path / "strip.png") is not None


def _pdf(path: Path, lines: list[str]) -> Path:
    """A minimal one-page text PDF written by hand (no extra dependency)."""
    ops = ["BT", "/F1 12 Tf", "72 760 Td", "16 TL"]
    for ln in lines:
        ops.append(f"({ln}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)
    return path


def test_pdf_md_txt_are_parsed(tmp_path):
    pdf = _pdf(tmp_path / "guide.pdf", ["User guide", "1. Getting started", "Open the registry and press the Add button.",
                                        "2. Filters", "Use the = operator for exact match."])
    md = tmp_path / "notes.md"
    md.write_text("---\ntitle: Заметки\n---\n# 1 Раздел\n\nТекст раздела.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    txt = tmp_path / "plain.txt"
    txt.write_text("1 Введение\nПростой текст без разметки.\n", encoding="utf-8")
    assert {p.suffix for p in collect_files([tmp_path])} == {".pdf", ".md", ".txt"}
    assert {".docx", ".pdf", ".md", ".txt"} <= SUPPORTED

    pdf_doc = parse_file(pdf, tmp_path / "img")
    text = " ".join(b.text or "" for b in pdf_doc.blocks)
    assert "Open the registry and press the Add button." in text and "Use the = operator" in text
    md_doc = parse_file(md, tmp_path / "img")
    assert md_doc.title == "Заметки" and any(b.kind == "table" and b.rows[1] == ["1", "2"] for b in md_doc.blocks)
    txt_doc = parse_file(txt, tmp_path / "img")
    assert [b.text for b in txt_doc.blocks if b.kind == "heading"] == ["1 Введение"]
    with pytest.raises(ValueError):
        parse_file(tmp_path / "x.rtf", tmp_path / "img")
