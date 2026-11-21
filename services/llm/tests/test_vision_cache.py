"""Image descriptions are cached per model: a change of VISION_MODEL describes the pictures again (FR-ING-04)."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import rag_service.api.app as app_mod
import rag_service.ingest.vision as vision
from rag_service.config import get_settings
from rag_service.llm import LLMUnavailable


@pytest.fixture
def picture(tmp_path):
    p = tmp_path / "shot.png"
    Image.new("RGB", (200, 120), (255, 255, 255)).save(p)
    return str(p)


@pytest.fixture
def setup(monkeypatch, tmp_path):
    """A fake vision model that counts calls and names itself in the description."""
    s = get_settings()
    cache = tmp_path / "cache"
    monkeypatch.setattr(s, "vision_cache_dir", str(cache))
    monkeypatch.setattr(s, "vision_cache_legacy", False)
    calls = []

    def fake_chat(*, model, **kw):
        used = model.split(",")[0]
        calls.append(used)
        resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(
            {"kind": "screenshot", "title": "Экран", "description": f"описание от {used}", "ocr_text": "Кнопка"})))])
        resp._model_used = used
        return resp

    monkeypatch.setattr(vision, "chat", fake_chat)
    return s, cache, calls


def test_model_change_describes_again_and_both_stay_cached(setup, picture, monkeypatch):
    s, cache, calls = setup
    monkeypatch.setattr(s, "vision_model", "vendor/model-a")
    first = vision.describe_image(picture, "doc/img1")
    assert first.description == "описание от vendor/model-a" and first.model == "vendor/model-a"
    assert vision.describe_image(picture, "doc/img1").description == first.description and calls == ["vendor/model-a"]

    monkeypatch.setattr(s, "vision_model", "vendor/model-b")
    second = vision.describe_image(picture, "doc/img1")
    assert second.description == "описание от vendor/model-b" and second.model == "vendor/model-b"
    assert calls == ["vendor/model-a", "vendor/model-b"]

    monkeypatch.setattr(s, "vision_model", "vendor/model-a")  # back: the first description is still there
    assert vision.describe_image(picture, "doc/img1").description == "описание от vendor/model-a"
    assert len(calls) == 2 and len(list(cache.glob("*.json"))) == 2


def test_chain_and_provider_pin(setup, picture, monkeypatch):
    s, cache, calls = setup
    assert vision.chain_models("a/x@Baseten, b/y ,") == ["a/x", "b/y"] and vision.chain_models("") == []
    monkeypatch.setattr(s, "vision_model", "vendor/model-b")
    vision.describe_image(picture, "doc/img1")
    # the described model is the fallback of another chain: its description is reused, in chain order
    monkeypatch.setattr(s, "vision_model", "vendor/model-a@Provider,vendor/model-b")
    info = vision.describe_image(picture, "doc/img1")
    assert info.model == "vendor/model-b" and calls == ["vendor/model-b"]
    name = vision.cache_path(cache, "f" * 64, "Vendor/Model-A@Provider").name
    assert name.endswith("_vendor-model-a.json") and name.startswith("f" * 24 + "_" + vision.VISION_PROMPT_VERSION)


def test_legacy_files_without_model_in_the_name(setup, picture, monkeypatch):
    s, cache, calls = setup
    cache.mkdir()
    digest = vision.sha256_file(picture)
    legacy = cache / f"{digest[:24]}_{vision.VISION_PROMPT_VERSION}.json"
    legacy.write_text(json.dumps({"kind": "dialog", "description": "старое описание", "_model": "old/model"}), encoding="utf-8")

    monkeypatch.setattr(s, "vision_model", "vendor/model-a")
    assert vision.describe_image(picture, "doc/img1").description == "описание от vendor/model-a"  # another model: ignored
    assert calls == ["vendor/model-a"]

    monkeypatch.setattr(s, "vision_model", "new/model,old/model")  # the old model is in the chain: its file counts
    info = vision.describe_image(picture, "doc/img1")
    assert info.description == "старое описание" and info.model == "old/model" and len(calls) == 1

    monkeypatch.setattr(s, "vision_model", "vendor/model-c")
    monkeypatch.setattr(s, "vision_cache_legacy", True)  # explicit consent to keep whatever model wrote it
    assert vision.describe_image(picture, "doc/img1").description == "старое описание" and len(calls) == 1


def test_unavailable_model_writes_nothing(setup, picture, monkeypatch):
    s, cache, _ = setup
    monkeypatch.setattr(s, "vision_model", "vendor/model-a")

    def down(**kw):
        raise LLMUnavailable("no credits")

    monkeypatch.setattr(vision, "chat", down)
    info = vision.describe_image(picture, "doc/img1")
    assert info.description == "" and info.model == "" and not list(cache.glob("*.json"))
    assert vision.describe_image("/no/such/file.png", "doc/img2").broken


def test_images_endpoint_lists_index_text(monkeypatch):
    kb = {"generation": "g1",
          "chunks": [{"chunk_type": "text", "image_ids": ["d/a"], "text": "текст рядом", "document_title": "Док", "section_path": ["1"], "page": 2},
                     {"chunk_type": "image", "image_ids": ["d/a"], "text": "чанк картинки", "document_title": "Док",
                      "section_path": ["1 Раздел", "1.1"], "page": 3}],
          "images": {"d/a": {"kind": "bpmn", "title": "Схема", "description": "описание", "ocr_text": "Да | Нет", "model": "vlm-x",
                             "crop_path": "/x.png"},
                     "d/b": {"kind": "broken", "broken": True}}}
    monkeypatch.setattr(app_mod, "get_kb", lambda pid: kb)
    data = TestClient(app_mod.app).get("/images").json()
    assert data["generation"] == "g1" and [i["image_id"] for i in data["images"]] == ["d/a", "d/b"]
    a, b = data["images"]
    assert a["text"] == "чанк картинки" and a["page"] == 3 and a["section_path"] == "1 Раздел → 1.1"  # the image chunk, not the text one
    assert a["model"] == "vlm-x" and a["has_crop"] and a["document_title"] == "Док" and a["ocr_text"] == "Да | Нет"
    assert b["broken"] and b["text"] == "" and b["model"] is None and b["document_title"] is None


def test_vision_modes_add_or_replace_with_ocr(setup, picture, monkeypatch):
    import rag_service.ingest.ocr as ocr

    s, cache, calls = setup
    monkeypatch.setattr(s, "vision_model", "vendor/model-a")
    reads = []
    monkeypatch.setattr(ocr, "read_lines", lambda path, min_score=0.5: reads.append(path) or ["Телефон: 4900", "Неотложный 2 ч"])
    monkeypatch.setattr(ocr, "_engine", object())  # pretend the engine is up, so the result is cached

    monkeypatch.setattr(s, "vision_mode", "vlm+ocr")
    both = vision.describe_image(picture, "doc/img1")
    assert both.description == "описание от vendor/model-a" and both.ocr_lines == "Телефон: 4900 | Неотложный 2 ч"
    assert vision.describe_image(picture, "doc/img1").ocr_lines == both.ocr_lines and len(reads) == 1  # cached

    monkeypatch.setattr(s, "vision_mode", "ocr")
    only = vision.describe_image(picture, "doc/img1")
    assert only.description == "" and only.model == "ocr" and only.ocr_lines == both.ocr_lines
    assert calls == ["vendor/model-a"]  # the vision model is not called in ocr mode

    monkeypatch.setattr(s, "vision_mode", "vlm")
    assert vision.describe_image(picture, "doc/img1").ocr_lines == ""


def test_ocr_unavailable_is_skipped_and_not_cached(tmp_path, monkeypatch):
    import rag_service.ingest.ocr as ocr

    monkeypatch.setattr(ocr, "_engine", None)
    monkeypatch.setattr(ocr, "_engine_error", "rapidocr is not installed")
    assert ocr.read_lines(tmp_path / "x.png") == []
    assert ocr.cached_lines(tmp_path / "x.png", "a" * 64, tmp_path) == [] and not list(tmp_path.glob("*.json"))


def test_prompt_v2_asks_for_both_branches(monkeypatch):
    s = get_settings()
    assert vision.SYSTEM_V2 != vision.SYSTEM and "обе ветки" in vision.SYSTEM_V2
    monkeypatch.setattr(s, "vision_prompt", "v2")
    system, version = vision.prompt()
    assert system is vision.SYSTEM_V2 and version != vision.VISION_PROMPT_VERSION
    monkeypatch.setattr(s, "vision_prompt", "v1")
    assert vision.prompt() == (vision.SYSTEM, vision.VISION_PROMPT_VERSION)
    monkeypatch.setattr(s, "vision_prompt", "unknown")
    assert vision.prompt()[1] == vision.VISION_PROMPT_VERSION


def test_image_chunk_carries_ocr_section():
    from rag_service.ingest.blocks import Block, ParsedDocument
    from rag_service.ingest.chunker import ImageInfo, chunk_document

    doc = ParsedDocument(title="Док", doc_id="doc", source_file="d.md", blocks=[
        Block("heading", "1 Раздел", level=2), Block("paragraph", "Окно поддержки:"), Block("image", image_path="/x/p01.png", alt="скрин")])
    info = ImageInfo(image_id="doc/p01", path="/x/p01.png", kind="screenshot", title="Поддержка", description="окно",
                     ocr_text="Servicedesk", ocr_lines="Телефон: 4900")
    chunks = chunk_document(doc, {"doc/p01": info}, lambda p: "doc/p01", max_tokens=400, target_tokens=300, table_max_tokens=300)
    text = next(c.text for c in chunks if c.chunk_type == "image")
    assert "Описание изображения: окно" in text and "Надписи на изображении: Servicedesk" in text
    assert text.rstrip().endswith("Текст с изображения (OCR): Телефон: 4900")


def test_user_screenshot_reading_gets_ocr_lines(monkeypatch):
    import base64 as b64

    import rag_service.ingest.ocr as ocr

    s = get_settings()
    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(
        {"screen": "окно ошибки", "error_text": "Возникла исключительная ситуация", "search_query": "исключительная ситуация"})))])
    monkeypatch.setattr(vision, "chat", lambda **kw: reply)
    monkeypatch.setattr(ocr, "read_lines", lambda path, min_score=0.5: ["Возникла исключительная ситуация,", "Перезагрузить"])
    images = [{"mime": "image/png", "data_base64": b64.b64encode(b"\x89PNG fake").decode()}]

    monkeypatch.setattr(s, "user_image_ocr", False)
    assert "ocr_lines" not in vision.describe_user_images(images, "что делать?")
    monkeypatch.setattr(s, "user_image_ocr", True)
    data = vision.describe_user_images(images, "что делать?")
    assert data["ocr_lines"] == "Возникла исключительная ситуация, | Перезагрузить"
    assert data["search_query"] == "исключительная ситуация"  # the query stays the model's
