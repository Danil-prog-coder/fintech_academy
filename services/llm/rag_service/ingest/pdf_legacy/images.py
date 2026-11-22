"""Extract embedded raster images from a PDF without PyMuPDF (AGPL).

Uses pypdf (BSD-3-Clause) to decode XObjects and pdfplumber (MIT) for
placement boxes. Images are saved as PNG.
"""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from .models import Block


def _safe_name(name: str) -> str:
    name = (name or "img").lstrip("/")
    name = re.sub(r"\.(jp2|jpx|jpg|jpeg|png|bmp|tif|tiff)$", "", name, flags=re.I)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name) or "img"


def _to_png_bytes(image) -> bytes | None:
    pil = getattr(image, "image", None)
    if pil is None:
        data = getattr(image, "data", None)
        if not data:
            return None
        from io import BytesIO

        from PIL import Image

        try:
            pil = Image.open(BytesIO(data))
        except Exception:
            return None
    from io import BytesIO

    if pil.mode not in ("RGB", "RGBA", "L"):
        pil = pil.convert("RGBA" if "A" in pil.mode else "RGB")
    buf = BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def extract_pdf_images(pdf_path: str | Path, out_dir: str | Path, doc_slug: str) -> list[Block]:
    """Save images and return placeholder Blocks in page order."""
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    import pdfplumber

    reader = PdfReader(str(pdf_path))
    blocks: list[Block] = []
    saved: dict[tuple[int, str], str] = {}

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_idx, (ppage, rpage) in enumerate(zip(pdf.pages, reader.pages)):
            page_no = page_idx + 1
            placements = list(ppage.images or [])
            # Decode unique XObjects on this page
            xobjects: dict[str, object] = {}
            for image in getattr(rpage, "images", []) or []:
                raw = _safe_name(getattr(image, "name", "") or "")
                xobjects[raw] = image
                # also index without Image prefix variants
                xobjects[getattr(image, "name", "").lstrip("/")] = image

            if not placements and not xobjects:
                continue

            # If pypdf found images but plumber placements are missing, still save them
            used = set()
            for n, im in enumerate(placements, start=1):
                raw_name = _safe_name(str(im.get("name") or f"img{n}"))
                image_obj = (
                    xobjects.get(raw_name)
                    or xobjects.get(im.get("name", ""))
                    or xobjects.get("/" + raw_name)
                )
                # skip tiny decorative dots (< 8 px on both sides and small PDF box)
                px_w = px_h = None
                try:
                    stream = im.get("stream")
                    if stream is not None:
                        px_w = int(stream.get("Width") or 0)
                        px_h = int(stream.get("Height") or 0)
                except Exception:
                    pass
                pdf_w = float(im.get("width") or 0)
                pdf_h = float(im.get("height") or 0)
                if (px_w and px_h and px_w < 8 and px_h < 8) or (pdf_w < 6 and pdf_h < 6):
                    continue

                rel = saved.get((page_no, raw_name))
                if rel is None and image_obj is not None:
                    png = _to_png_bytes(image_obj)
                    if png:
                        fname = f"{doc_slug}_p{page_no:02d}_{n:02d}_{raw_name}.png"
                        dest = out_dir / fname
                        dest.write_bytes(png)
                        rel = f"images/{fname}"
                        saved[(page_no, raw_name)] = rel
                if rel is None:
                    # still record a placeholder even if decode failed
                    fname = f"{doc_slug}_p{page_no:02d}_{n:02d}_{raw_name}.missing"
                    rel = f"images/{fname}"

                used.add(raw_name)
                top = float(ppage.height) - float(im.get("y1") or 0)
                bottom = float(ppage.height) - float(im.get("y0") or 0)
                bbox = (
                    float(im.get("x0") or 0),
                    top,
                    float(im.get("x1") or 0),
                    bottom,
                )
                blocks.append(
                    Block(
                        typ="image",
                        text="",
                        page=page_no,
                        bbox=bbox,
                        image_ref=rel,
                        meta={
                            "pdf_width": pdf_w,
                            "pdf_height": pdf_h,
                            "px_width": px_w,
                            "px_height": px_h,
                            "xobject": raw_name,
                        },
                    )
                )

    blocks.sort(key=lambda b: (b.page, b.bbox[1] if b.bbox else 0, b.bbox[0] if b.bbox else 0))
    return blocks
