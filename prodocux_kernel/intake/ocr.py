"""Optional OCR fallback for scanned PDF pages (deterministic when engine is pinned)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

PathLike = Union[str, Path]


def ocr_availability() -> Dict[str, Any]:
    """Report whether OCR dependencies are importable."""
    info: Dict[str, Any] = {"available": False}
    try:
        import pytesseract  # noqa: WPS433

        info["pytesseract"] = getattr(pytesseract, "__version__", "unknown")
    except ImportError as exc:
        info["error"] = f"pytesseract not installed: {exc}"
        return info
    try:
        version = pytesseract.get_tesseract_version()
        info["tesseract"] = str(version)
        info["available"] = True
    except Exception as exc:
        info["error"] = f"tesseract binary unavailable: {exc}"
    return info


def ocr_pdf_page(
    pdf_path: PathLike,
    page_number: int,
    *,
    scale: float = 2.0,
    lang: str = "eng+chi_tra",
) -> Tuple[str, Dict[str, Any]]:
    """Render a PDF page and OCR it. Returns (text, metadata). Empty text if unavailable."""
    meta: Dict[str, Any] = {"engine": "pytesseract", "page": page_number, "scale": scale, "lang": lang}
    avail = ocr_availability()
    meta.update(avail)
    if not avail.get("available"):
        return "", meta

    from .pdf_images import render_pdf_page

    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / f"page_{page_number}.png"
        path, err = render_pdf_page(pdf_path, page_number, png, scale=scale)
        if err or not path:
            meta["error"] = err or "render failed"
            return "", meta
        import pytesseract  # noqa: WPS433
        from PIL import Image  # noqa: WPS433

        text = pytesseract.image_to_string(Image.open(path), lang=lang)
        meta["char_count"] = len(text)
        return text.strip(), meta
