"""Deterministic PDF page rendering and embedded-image extraction (CR-001 follow-up)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

PathLike = Union[str, Path]


def pymupdf_available() -> Tuple[bool, Optional[str]]:
    """Return (is_available, error_message)."""
    try:
        import fitz  # noqa: WPS433

        _ = fitz
        return True, None
    except ImportError as exc:
        return False, f"pymupdf not installed: {exc}"


def _pymupdf_version() -> str:
    ok, _ = pymupdf_available()
    if not ok:
        return "unknown"
    import fitz  # noqa: WPS433

    return str(getattr(fitz, "__version__", getattr(fitz, "VersionBind", "unknown")))


def render_pdf_page(
    pdf_path: PathLike,
    page_number: int,
    output_path: PathLike,
    *,
    scale: float = 2.0,
) -> Tuple[Optional[Path], Optional[str]]:
    """Render one PDF page to PNG via PyMuPDF. Returns (path, error)."""
    src = Path(pdf_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fitz  # noqa: WPS433
    except ImportError as exc:
        return None, f"pymupdf not installed: {exc}"

    try:
        doc = fitz.open(str(src))
        try:
            if page_number < 1 or page_number > doc.page_count:
                return None, f"page {page_number} out of range (1-{doc.page_count})"
            page = doc.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            pixmap.save(str(out))
        finally:
            doc.close()
    except Exception as exc:
        return None, str(exc)
    return out, None


def extract_embedded_page_image(
    pdf_path: PathLike,
    page_number: int,
    output_path: PathLike,
    *,
    image_index: int = 0,
) -> Tuple[Optional[Path], Optional[str]]:
    """Extract the Nth embedded image on a page via pypdf. Returns (path, error)."""
    src = Path(pdf_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        from pypdf import PdfReader  # noqa: WPS433
    except ImportError as exc:
        return None, f"pypdf not installed: {exc}"

    try:
        reader = PdfReader(str(src))
        if page_number < 1 or page_number > len(reader.pages):
            return None, f"page {page_number} out of range (1-{len(reader.pages)})"
        images = getattr(reader.pages[page_number - 1], "images", [])
        if not images:
            return None, "no embedded images on page"
        if image_index >= len(images):
            return None, f"image index {image_index} out of range ({len(images)} images)"
        image = images[image_index]
        suffix = Path(image.name).suffix or out.suffix or ".jpg"
        target = out.with_suffix(suffix)
        target.write_bytes(image.data)
    except Exception as exc:
        return None, str(exc)
    return target, None


def extract_evidence_item(
    pdf_path: PathLike,
    item: Dict[str, Any],
    image_dir: PathLike,
) -> Dict[str, Any]:
    """Extract one evidence spec item. Returns result record for evidence_index."""
    method = item.get("method", "render")
    page = int(item["page"])
    item_id = str(item["id"])
    filename = str(item.get("filename") or f"{item_id}.png")
    out_path = Path(image_dir) / filename
    scale = float(item.get("scale", 2.0))
    image_index = int(item.get("image_index", 0))

    if method == "embedded":
        path, err = extract_embedded_page_image(pdf_path, page, out_path, image_index=image_index)
        engine = "pypdf"
    elif method == "render":
        path, err = render_pdf_page(pdf_path, page, out_path, scale=scale)
        engine = "pymupdf"
    else:
        return {
            "id": item_id,
            "page": page,
            "method": method,
            "path": None,
            "error": f"unknown method: {method}",
        }

    rec: Dict[str, Any] = {
        "id": item_id,
        "page": page,
        "method": method,
        "engine": engine,
        "path": str(path.resolve()) if path else None,
    }
    if path and path.is_file():
        rec["size_bytes"] = path.stat().st_size
    if err:
        rec["error"] = err
    return rec


def extract_evidence_bundle(
    pdf_path: PathLike,
    spec: Dict[str, Any],
    image_dir: PathLike,
) -> Dict[str, Any]:
    """Extract all images listed in an evidence spec. Returns evidence_index envelope."""
    from .pdf import _sha256_file

    src = Path(pdf_path)
    out_dir = Path(image_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    images: Dict[str, Path] = {}
    records: List[Dict[str, Any]] = []

    for item in spec.get("extract", []):
        rec = extract_evidence_item(src, item, out_dir)
        records.append(rec)
        if rec.get("path"):
            images[rec["id"]] = Path(rec["path"])

    try:
        sha = _sha256_file(src)
    except OSError:
        sha = ""

    return {
        "schema": "prodocux_evidence_index_v1",
        "source_pdf": str(src.resolve()),
        "sha256": sha,
        "render_engine": "pymupdf",
        "render_engine_version": _pymupdf_version(),
        "image_dir": str(out_dir.resolve()),
        "images": records,
        "image_paths": {k: str(v) for k, v in images.items()},
    }
