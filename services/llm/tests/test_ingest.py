"""Parsing + chunking of the real knowledge base (FR-ING-01..05), no LLM / no embeddings."""

from pathlib import Path

import pytest

from rag_service.ingest.chunker import chunk_document, split_sections
from rag_service.ingest.md_parser import parse_markdown
from rag_service.ingest.pipeline import image_id_for

KB = Path(__file__).resolve().parent.parent / "data" / "demo_kb"


@pytest.fixture(scope="module")
def bp():
    return parse_markdown(KB / "bp_komandirovka.md")


def _chunks(doc):
    return chunk_document(doc, {}, image_id_for(doc.doc_id), max_tokens=650, target_tokens=420, table_max_tokens=500, warnings=[])


def test_bp_sections_hierarchy(bp):
    paths = [" → ".join(s.path) for s in split_sections(bp)]
    top = {p.split(" → ")[0].split()[0] for p in paths if p}
    for n in ["1", "2", "3", "4", "5", "6"]:
        assert n in top, (n, top)
    assert any("6.1" in p for p in paths) and any("6.3" in p for p in paths)


def test_chunks_have_anchors_and_types(bp):
    chunks = _chunks(bp)
    assert chunks
    for c in chunks:
        assert c.doc_id == bp.doc_id and c.section_path, c.chunk_id
    assert any(c.chunk_type == "image" for c in chunks)
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_om_duty_schedule_is_in_one_chunk(bp):
    texts = [c.text for c in _chunks(bp)]
    assert any("17:30" in t and "10:30" in t for t in texts)


def test_funnel_threshold_kept(bp):
    assert any(">= 60%" in c.text or "≥ 60" in c.text for c in _chunks(bp))


def test_furniture_registry_statuses():
    doc = parse_markdown(KB / "reestr_mebeli.md")
    texts = " ".join(c.text for c in _chunks(doc))
    for s in ["занят", "свободен", "списан"]:
        assert s in texts
    assert "Реестр техники" not in texts


def test_chunk_sizes_bounded():
    from rag_service.ingest.chunker import ntokens

    doc = parse_markdown(KB / "bars_office.md")
    assert max(ntokens(c.text) for c in _chunks(doc)) <= 900
