"""Classic OCR of Cyrillic text on images — an optional verbatim channel next to the vision model (FR-ING-04).

PP-OCRv5 detection + the East-Slavic recognition model (`eslav`) through RapidOCR on ONNX Runtime, CPU only
(RapidOCR and the models: Apache-2.0; onnxruntime: MIT). It reads text line by line and does not understand the
picture: it does not know where an element is, what an icon looks like or which arrow of a diagram an
«Да» belongs to. That is why it never replaces the vision model; VISION_MODE decides how they are combined
(`ingest/vision.py`).

The models are not downloaded at run time: put the four files into OCR_MODELS_DIR (see `MODEL_FILES`;
source — the RapidOCR model repository, onnx/PP-OCRv5). Without the package or the files OCR is skipped
with a warning, and indexing goes on with the vision model alone.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from ..core.config import get_settings

log = logging.getLogger(__name__)
OCR_VERSION = "ocr-ppocrv5-eslav-1"  # part of the cache key: a new model or post-processing → new texts
MODEL_FILES = {
    "det": "ch_PP-OCRv5_det_mobile.onnx",
    "cls": "ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx",
    "rec": "eslav_PP-OCRv5_rec_mobile.onnx",
    "dict": "ppocrv5_eslav_dict.txt",
}
_engine = None
_engine_error: str | None = None
_lock = threading.Lock()


def models_dir() -> Path:
    s = get_settings()
    if s.ocr_models_dir:
        return Path(s.ocr_models_dir)
    try:
        import rapidocr

        return Path(rapidocr.__file__).parent / "models"
    except ImportError:
        return Path(s.state_dir) / "ocr_models"


def _get_engine():
    """One engine per process (ONNX sessions are reusable across threads under a lock); None if unavailable."""
    global _engine, _engine_error
    if _engine is not None or _engine_error is not None:
        return _engine
    with _lock:
        if _engine is not None or _engine_error is not None:
            return _engine
        try:
            from rapidocr import LangRec, OCRVersion, RapidOCR
        except ImportError:
            _engine_error = "rapidocr is not installed (pip install .[ocr])"
            log.warning("OCR skipped: %s", _engine_error)
            return None
        d = models_dir()
        missing = [f for f in MODEL_FILES.values() if not (d / f).exists()]
        if missing:
            _engine_error = f"OCR model files missing in {d}: {missing}"
            log.warning("OCR skipped: %s", _engine_error)
            return None
        _engine = RapidOCR(params={
            "Det.model_path": str(d / MODEL_FILES["det"]), "Det.ocr_version": OCRVersion.PPOCRV5,
            "Cls.model_path": str(d / MODEL_FILES["cls"]), "Cls.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_path": str(d / MODEL_FILES["rec"]), "Rec.rec_keys_path": str(d / MODEL_FILES["dict"]),
            "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.lang_type": LangRec.ESLAV, "Global.log_level": "error",
        })
        return _engine


def read_lines(path: str | Path, min_score: float = 0.5) -> list[str]:
    """Text lines of the image, top to bottom, without low-confidence fragments; [] if OCR is unavailable."""
    engine = _get_engine()
    if engine is None:
        return []
    with _lock:
        result = engine(str(path))
    texts = list(result.txts or [])
    scores = list(result.scores or [1.0] * len(texts))
    return [t.strip() for t, sc in zip(texts, scores, strict=False) if t and t.strip() and sc >= min_score]


def cached_lines(path: str | Path, digest: str, cache_dir: Path) -> list[str]:
    """OCR lines cached next to the vision descriptions (key: sha256 of the image + OCR_VERSION)."""
    f = cache_dir / f"{digest[:24]}_{OCR_VERSION}.json"
    if f.exists():
        return list(json.loads(f.read_text(encoding="utf-8")).get("lines") or [])
    lines = read_lines(path)
    if lines or _engine is not None:  # an unavailable engine must not leave an empty «result» in the cache
        f.write_text(json.dumps({"lines": lines, "_ocr": OCR_VERSION}, ensure_ascii=False, indent=1), encoding="utf-8")
    return lines
