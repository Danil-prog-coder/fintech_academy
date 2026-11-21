"""A PDF page without a text layer (a scan) is reported, and its text reaches the index only through the vision model."""

from PIL import Image, ImageDraw

from rag_service.ingest.blocks import Block, ParsedDocument
from rag_service.ingest.pipeline import build_chunks, pages_without_text_layer


def test_pages_without_text_layer():
    doc = ParsedDocument(title="Д", doc_id="d", source_file="d.pdf", blocks=[
        Block("heading", "1 Раздел с текстом и картинкой", page=1), Block("paragraph", "Обычный текстовый слой страницы. " * 3, page=1),
        Block("image", image_path="/x/p1.png", page=1),
        Block("image", image_path="/x/p2.png", page=2),  # скан: только картинка
        Block("paragraph", "стр. 3", page=3), Block("image", image_path="/x/p3.png", page=3),  # скан с номером страницы
        Block("paragraph", "Страница без картинок, но с текстом.", page=4),
    ])
    assert pages_without_text_layer(doc) == [2, 3]


def test_scanned_pdf_is_flagged_in_the_indexing_report(tmp_path):
    im = Image.new("RGB", (900, 400), "white")
    ImageDraw.Draw(im).text((40, 40), "Scanned page: 17:30 - 21:00", fill="black")
    pdf = tmp_path / "scan.pdf"
    im.save(pdf, "PDF", resolution=100.0)
    chunks, images, report = build_chunks([pdf], describe=False)
    assert len(images) == 1  # the page picture is extracted, so a vision model could read it
    assert any(w.endswith("page_without_text_layer: p.1 (not described: the page text is lost)") for w in report["warnings"])
