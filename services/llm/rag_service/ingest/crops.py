"""Red-frame crops (FR-ING-06): for a screenshot where an element is highlighted with a red rectangle, store the
cut-out of that element (with a margin) so the bot can send just the highlighted part (FR-VIS-02)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def _components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    """4-connected components of a boolean mask (8-neighbourhood to bridge anti-aliased corners)."""
    seen = np.zeros_like(mask, dtype=bool)
    h, w = mask.shape
    comps = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        stack, comp = [(int(y0), int(x0))], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            comp.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        comps.append(comp)
    return comps


def red_frame_bbox(path: str | Path, *, min_side: int = 12) -> tuple[int, int, int, int] | None:
    """Bounding box (x0, y0, x1, y1) of highlight frame(s) in original pixels, or None.

    Documentation screenshots highlight elements with hollow rectangles of a saturated colour (red or bright blue).
    A component counts as a frame when it is hollow (pixel count ≈ perimeter × line width), all four sides are
    drawn, and it covers 0.1–85 % of the image — so filled UI elements, arrows and red text are ignored.
    """
    im = Image.open(path).convert("RGB")
    w, h = im.size
    if w < 40 or h < 20:
        return None
    scale = min(1.0, 700 / max(w, h))
    small = im.resize((max(1, int(w * scale)), max(1, int(h * scale)))) if scale < 1 else im
    a = np.asarray(small).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    masks = [(r > 170) & (r - np.maximum(g, b) > 90),  # red
             (b > 180) & (b - np.maximum(r, g) > 90) & (r < 120)]  # bright blue
    boxes = []
    total = a.shape[0] * a.shape[1]
    for mask in masks:
        if mask.sum() < 20 or mask.sum() > 0.3 * total:
            continue
        for comp in _components(mask):
            ys = np.array([p[0] for p in comp])
            xs = np.array([p[1] for p in comp])
            x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
            bw, bh = x1 - x0 + 1, y1 - y0 + 1
            if bw < min_side * scale or bh < min_side * scale or not (0.001 <= bw * bh / total <= 0.85):
                continue
            ratio = len(comp) / (2 * (bw + bh))
            if not (0.5 <= ratio <= 5):
                continue  # filled area or a thin diagonal (arrow)
            cm = np.zeros((bh, bw), dtype=bool)
            cm[ys - y0, xs - x0] = True
            edge = max(1, int(round(3 * scale)) + 1)
            sides = [cm[:edge].any(axis=0).mean(), cm[-edge:].any(axis=0).mean(),
                     cm[:, :edge].any(axis=1).mean(), cm[:, -edge:].any(axis=1).mean()]
            if min(sides) >= 0.7:
                boxes.append((x0, y0, x1, y1))
    if not boxes:
        return None
    x0, y0 = min(bx[0] for bx in boxes), min(bx[1] for bx in boxes)
    x1, y1 = max(bx[2] for bx in boxes), max(bx[3] for bx in boxes)
    inv = 1 / scale
    return int(x0 * inv), int(y0 * inv), int(x1 * inv) + 1, int(y1 * inv) + 1


def crop_red_frame(path: str | Path, out: str | Path, margin: int = 12) -> bool:
    bbox = red_frame_bbox(path)
    if not bbox:
        return False
    im = Image.open(path)
    w, h = im.size
    x0, y0, x1, y1 = bbox
    box = (max(0, x0 - margin), max(0, y0 - margin), min(w, x1 + margin), min(h, y1 + margin))
    if (box[2] - box[0]) * (box[3] - box[1]) > 0.9 * w * h:
        return False  # the frame is (almost) the whole picture — nothing to cut out
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    im.crop(box).save(out)
    return True
