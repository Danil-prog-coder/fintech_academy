"""Image -> text at indexing time via a VLM (FR-ING-04), cached on disk.

Every image is classified and described with a template for its type. Results are cached by
sha256(image) + prompt version + model, so re-indexing is free and deterministic, and a change of
VISION_MODEL re-describes the images instead of reusing another model's text.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from pathlib import Path

from PIL import Image

from ..core.config import get_settings
from ..llm import LLMUnavailable, chat
from .chunker import ImageInfo
from .util import sha256_file

log = logging.getLogger(__name__)
VISION_PROMPT_VERSION = "vis-2026-11-13.2"  # v1; the active version comes from prompt()

SYSTEM = """Ты индексируешь изображения из корпоративной документации (интерфейс системы «БАРС-Офис», бизнес-процессы, реестры).
Описание будет использоваться для поиска и ответов на вопросы «как выглядит кнопка», «где найти элемент», «какие условия в схеме».
Пиши по-русски, только то, что реально видно на изображении. Надписи переписывай дословно. Ничего не выдумывай.
Верни строго JSON-объект с полями:
{
 "kind": "screenshot" | "annotated_screenshot" | "button_panel" | "bpmn" | "dialog" | "icon" | "photo" | "video_thumbnail" | "broken" | "other",
 "title": "короткое название (что изображено), до 12 слов",
 "description": "подробное описание по шаблону типа (см. ниже)",
 "ocr_text": "все видимые надписи через « | »",
 "rules": ["для bpmn: правила вида «если … то следующий шаг …»"]
}
Шаблоны:
- screenshot: название экрана/окна, области (верх/низ/лево/право), все видимые подписи, поля и колонки таблиц, элементы управления и где они расположены.
- annotated_screenshot (красные подписи, стрелки, рамки, номера (1), (2)): как screenshot + отдельный список «метка → на какой элемент указывает».
- button_panel: перечень кнопок СЛЕВА НАПРАВО: № — как выглядит иконка (форма, цвет), подпись (если есть), вероятное действие. Отметь, какая кнопка выделена рамкой.
- bpmn (схема бизнес-процесса): все узлы (задачи) с дословными подписями, все развилки (ромбы) с вопросами и подписями веток (Да/Нет), переходы со подписями, начальные и конечные состояния; затем связный текст о порядке прохождения.
- dialog: заголовок окна, поля, кнопки.
- icon: что изображено на иконке (форма, цвет).
- video_thumbnail: если это заглушка/превью видео — так и напиши.
- broken: если изображение пустое или это значок «картинка не загрузилась» (красный крестик).
"""

# v2: the diagram template asks for EVERY transition, both branches of every decision, labels taken from the lines.
# v1 gave free-text rules that skipped «Нет» branches (eval/golden/image_descriptions.yaml, IMG-BP-SCHEMA).
SYSTEM_V2 = SYSTEM.replace(
    "- bpmn (схема бизнес-процесса): все узлы (задачи) с дословными подписями, все развилки (ромбы) с вопросами и подписями веток (Да/Нет), переходы со подписями, начальные и конечные состояния; затем связный текст о порядке прохождения.",
    "- bpmn (схема бизнес-процесса): в description — все узлы (задачи, события, начальные и конечные состояния) с дословными подписями "
    "и связный текст о порядке прохождения. В rules — ПОЛНЫЙ список переходов схемы, по одному на строку, в виде "
    "«Откуда» — подпись линии → «Куда» (без подписи: «Откуда» → «Куда»). Для КАЖДОЙ развилки (ромба) обязательно обе ветки отдельными "
    "строками: «Вопрос?» — Да → … и «Вопрос?» — Нет → …. Подпись ветки бери строго с линии на схеме, даже если она противоречит "
    "тексту рядом: текст рядом не исправляет схему. Проверь, что ни один ромб и ни одна линия не пропущены.",
)
PROMPTS = {"v1": (SYSTEM, "vis-2026-11-13.2"), "v2": (SYSTEM_V2, "vis-2026-11-15.2")}


def prompt() -> tuple[str, str]:
    """(system prompt, version) selected by VISION_PROMPT; the version is part of the cache key."""
    return PROMPTS.get(get_settings().vision_prompt, PROMPTS["v1"])


def chain_models(chain: str) -> list[str]:
    """Models of a «a@Provider,b» chain without the provider pin, in order."""
    return [m.strip().partition("@")[0] for m in (chain or "").split(",") if m.strip()]


def _model_slug(model: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", model.partition("@")[0].lower()).strip("-")


def cache_path(cache_dir: Path, digest: str, model: str, version: str | None = None) -> Path:
    """Description file of one image made by one model: sha256 + prompt version + model."""
    return cache_dir / f"{digest[:24]}_{version or prompt()[1]}_{_model_slug(model)}.json"


def _cached_description(cache_dir: Path, digest: str, chain: str, accept_legacy: bool) -> dict | None:
    """A cached description made by a model of the configured chain (in chain order), or None.

    The model is part of the cache key: after VISION_MODEL changes, images are described again by the new
    model instead of silently keeping the old descriptions. Files written before the model became part of
    the key («<sha>_<prompt>.json») are used only when the model recorded inside them belongs to the chain,
    or when VISION_CACHE_LEGACY=true asks to keep them whatever model made them.
    """
    models = chain_models(chain)
    for m in models:
        f = cache_path(cache_dir, digest, m)
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    legacy = cache_dir / f"{digest[:24]}_{prompt()[1]}.json"
    if legacy.exists():
        data = json.loads(legacy.read_text(encoding="utf-8"))
        made_by = str(data.get("_model") or "").partition("@")[0]
        if accept_legacy or made_by in models:
            return data
    return None


def _prepare(path: str) -> tuple[str, tuple[int, int]]:
    im = Image.open(path)
    im = im.convert("RGB")
    w, h = im.size
    # small screenshots / low-res diagrams: upscale so the VLM can read small labels
    scale = 1.0
    if max(w, h) < 1600:
        scale = min(2.0, 2000 / max(w, h)) if max(w, h) > 60 else 4.0
    if scale > 1.01:
        im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode(), (w, h)


def looks_broken(path: str, dup_count: int) -> bool:
    """Tiny image repeated across the document = export placeholder (the red-cross icon)."""
    try:
        w, h = Image.open(path).size
    except Exception:
        return True
    if w * h < 64:
        return True
    if w <= 40 and h <= 40 and dup_count >= 2:
        # the Word "image not found" placeholder is a small frame with a red cross;
        # tiny repeated toolbar icons (magnifier etc.) are legitimate
        im = Image.open(path).convert("RGB")
        px = list(im.get_flattened_data()) if hasattr(im, "get_flattened_data") else list(im.getdata())
        red = sum(1 for r, g, b in px if r > 150 and g < 90 and b < 90) / max(len(px), 1)
        return red > 0.005
    return False


def describe_image(path: str, image_id: str, *, context: str = "", section: str = "", dup_count: int = 1) -> ImageInfo:
    s = get_settings()
    info = ImageInfo(image_id=image_id, path=path)
    if not Path(path).exists():
        info.broken = True
        info.kind = "broken"
        return info
    if looks_broken(path, dup_count):
        info.broken = True
        info.kind = "broken"
        info.title = "изображение не сохранилось при экспорте"
        return info
    digest = sha256_file(path)
    cache_dir = Path(s.vision_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    mode = (s.vision_mode or "vlm").lower()
    if mode in ("vlm+ocr", "ocr"):  # verbatim text of the picture from classic OCR (ingest/ocr.py)
        from .ocr import cached_lines

        info.ocr_lines = " | ".join(cached_lines(path, digest, cache_dir))
    if mode == "ocr":  # no vision model: the chunk carries the text around the picture and the OCR lines only
        info.kind, info.model = "other", "ocr"
        return info
    system, version = prompt()
    data = _cached_description(cache_dir, digest, s.vision_model, s.vision_cache_legacy)
    if data is None:
        b64, (w, h) = _prepare(path)
        user = (
            f"Раздел документа: {section}\nТекст рядом с изображением: {context or '—'}\n"
            f"Исходный размер: {w}x{h}px. Опиши изображение по шаблону его типа. Номера-метки (1), (2) свяжи с текстом рядом."
        )
        try:
            resp = chat(
                model=s.vision_model, reasoning_effort=s.user_vision_reasoning_effort or s.heavy_reasoning_effort or None,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": [
                        {"type": "text", "text": user},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ]},
                ],
                response_format={"type": "json_object"},
                retries=s.vision_retries,
            )
            raw = resp.choices[0].message.content or "{}"
            data = _parse_json(raw)
        except LLMUnavailable as e:
            log.warning("vision failed for %s: %s", image_id, e)
            return info  # no description; the chunk still carries context + alt text
        data["_model"] = getattr(resp, "_model_used", None) or chain_models(s.vision_model)[0]
        data["_prompt_version"] = version
        data["_image"] = image_id
        cache_path(cache_dir, digest, data["_model"], version).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    info.model = str(data.get("_model") or "")
    info.kind = str(data.get("kind") or "other")
    info.title = str(data.get("title") or "")
    desc = str(data.get("description") or "")
    rules = data.get("rules") or []
    if rules:
        desc += "\nПравила переходов:\n" + "\n".join(f"- {r}" for r in rules if r)
    info.description = desc.strip()
    info.ocr_text = str(data.get("ocr_text") or "")
    if info.kind == "broken":
        info.broken = True
    return info


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {"kind": "other", "description": raw}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"kind": "other", "description": raw}


USER_SYSTEM = """Пользователь службы поддержки прислал скриншот из корпоративной системы (обычно «БАРС-Офис»).
Прочитай его, чтобы по тексту можно было найти ответ в документации. Пиши по-русски, надписи переписывай дословно, ничего не выдумывай.
Верни строго JSON:
{"screen": "что за экран/окно", "error_text": "дословный текст ошибки или сообщения, если есть, иначе пусто",
 "ocr_text": "все видимые надписи через « | »", "elements": ["важные кнопки/поля/вкладки"],
 "description": "1–3 предложения: что видно и что, вероятно, пытается сделать пользователь",
 "search_query": "самостоятельный поисковый запрос по документации (с дословным текстом ошибки, если есть)"}"""


def describe_user_images(images: list[dict], user_text: str = "", deadline: float | None = None) -> dict | None:
    """FR-VIS-03: VLM reads the user's screenshot(s) at question time → text + search query for retrieval.

    Uses USER_VISION_MODEL (e.g. a GLM vision model on OpenRouter with a Gemini fallback); returns None when no model
    is available — the agent still sees the image itself as part of the message."""
    import time as _t

    s = get_settings()
    if not images:
        return None
    content: list[dict] = [{"type": "text", "text": f"Подпись пользователя: {user_text or '—'}"}]
    for im in images[:3]:
        content.append({"type": "image_url", "image_url": {"url": f"data:{im.get('mime', 'image/png')};base64,{im['data_base64']}"}})
    until = min(deadline or _t.time() + 25, _t.time() + 25)
    chain = [m.strip() for m in (s.user_vision_model or s.vision_model).split(",") if m.strip()]

    def call(model: str):
        return chat(model=model, retries=1, temperature=0, reasoning_effort=s.user_vision_reasoning_effort or s.heavy_reasoning_effort or None,
                    response_format={"type": "json_object"}, deadline=until,
                    messages=[{"role": "system", "content": USER_SYSTEM}, {"role": "user", "content": content}])

    try:
        if s.user_vision_hedge_after_s > 0 and len(chain) > 1:
            from ..llm import hedged_call

            resp = hedged_call(call, chain, s.user_vision_hedge_after_s, until - _t.time(), what="user screenshot VLM")
            if resp is None:
                return None
        else:
            resp = call(",".join(chain))
    except (LLMUnavailable, TimeoutError) as e:
        log.warning("user screenshot VLM unavailable: %s", e)
        return None
    data = _parse_json(resp.choices[0].message.content or "{}")
    data["_model"] = getattr(resp, "_model_used", None)
    q = str(data.get("search_query") or "").strip()
    if not q:
        q = " ".join(x for x in (user_text, str(data.get("error_text") or ""), str(data.get("screen") or "")) if x).strip()
    data["search_query"] = q[:300]
    if s.user_image_ocr:  # verbatim lines next to the model's reading (ingest/ocr.py); the agent sees both
        lines = _ocr_user_images(images[:3])
        if lines:
            data["ocr_lines"] = " | ".join(lines)
    return data


def _ocr_user_images(images: list[dict]) -> list[str]:
    import tempfile

    from .ocr import read_lines

    out: list[str] = []
    for im in images:
        try:
            raw = base64.b64decode(im["data_base64"])
        except (KeyError, ValueError):
            continue
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(raw)
            path = f.name
        try:
            out += read_lines(path)
        finally:
            Path(path).unlink(missing_ok=True)
    return out
