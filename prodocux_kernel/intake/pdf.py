"""CR-001: Deterministic PDF page text extraction.

Produces standard ``pages.json`` for ``map_sources_to_sections`` and provenance.
No LLM calls. Engine: pypdf (version pinned in output metadata).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]

PAGES_SCHEMA = "prodocux_pages_v1"
MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 50
MAX_PDF_PAGE_CHARS = 50_000
MAX_PDF_TOTAL_CHARS = 500_000
_EXTRACTION_ERROR_PREFIX = "[EXTRACTION_ERROR]"

_SOURCE_PAGES_HEADER = re.compile(
    r"^===\s*(?P<file>.+?)\s*\|\s*Page\s+(?P<page>\d+)\s*===\s*$",
    re.MULTILINE,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _engine_version() -> str:
    try:
        import pypdf  # noqa: WPS433

        return getattr(pypdf, "__version__", "unknown")
    except Exception:
        return "unknown"


def normalize_page_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize heterogeneous page dicts to ``{file, page, text}`` (+ extras)."""
    if "file" in record and "page" in record and "text" in record:
        file_name = str(record["file"])
        page_no = int(record["page"])
        text = str(record.get("text") or "")
    elif "Document_ID" in record and "Page_Number" in record:
        file_name = str(record["Document_ID"])
        page_no = int(record["Page_Number"])
        text = str(record.get("Extracted_Text") or record.get("text") or "")
    elif "Source_File" in record and "Page_Number" in record:
        src = Path(str(record["Source_File"]))
        file_name = str(record.get("Document_ID") or src.name)
        page_no = int(record["Page_Number"])
        text = str(record.get("Extracted_Text") or record.get("text") or "")
    else:
        raise ValueError(f"unrecognized page record keys: {sorted(record)}")

    out: Dict[str, Any] = {
        "file": file_name,
        "page": page_no,
        "text": text,
        "char_count": len(text),
    }
    if record.get("source_path"):
        out["source_path"] = str(record["source_path"])
    if text.startswith(_EXTRACTION_ERROR_PREFIX):
        out["extraction_error"] = text
    return out


def pages_for_mapping(pages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strip to the minimal shape consumed by ``map_sources_to_sections``."""
    return [
        {"file": p["file"], "page": p["page"], "text": p["text"]}
        for p in (normalize_page_record(r) for r in pages)
    ]


def extract_pdf_pages(
    pdf_path: PathLike,
    *,
    ocr_fallback: bool = False,
    ocr_min_chars: int = 20,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Extract text from each page of one PDF.

    Returns (pages, file_level_error). Page-level failures are recorded in
    ``text`` with ``[EXTRACTION_ERROR]`` prefix and ``extraction_error`` field.
    """
    path = Path(pdf_path)
    try:
        from pypdf import PdfReader  # noqa: WPS433
    except ImportError as exc:
        return [], f"pypdf not installed: {exc}"

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        return [], str(exc)

    pages: List[Dict[str, Any]] = []
    try:
        page_iter = enumerate(reader.pages, start=1)
    except Exception as exc:
        return [], str(exc)
    for idx, page in page_iter:
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            text = f"{_EXTRACTION_ERROR_PREFIX} {exc}"
        ocr_meta: Optional[Dict[str, Any]] = None
        if ocr_fallback and len(text.strip()) < ocr_min_chars and not text.startswith(_EXTRACTION_ERROR_PREFIX):
            from .ocr import ocr_pdf_page

            ocr_text, ocr_meta = ocr_pdf_page(path, idx)
            if ocr_text:
                text = ocr_text
        rec = normalize_page_record({
            "file": path.name,
            "page": idx,
            "text": text,
            "source_path": str(path.resolve()),
        })
        if ocr_meta and ocr_meta.get("available"):
            rec["ocr"] = True
            rec["ocr_engine"] = ocr_meta.get("engine")
            rec["ocr_tesseract"] = ocr_meta.get("tesseract")
        pages.append(rec)
    return pages, None


def extract_pdf_bytes(
    payload: bytes,
    *,
    filename: str,
    max_pages: int = MAX_PDF_PAGES,
    ocr_min_chars: int = 20,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Extract bounded page text from an in-memory PDF.

    Returns ``(pages, truncated)``. This HTTP-facing path intentionally does
    not persist the source bytes or expose a local source path.
    """
    if not payload:
        raise ValueError("document payload is empty")
    if len(payload) > MAX_PDF_BYTES:
        raise ValueError("document_b64 exceeds PDF intake limit")
    if not 1 <= max_pages <= MAX_PDF_PAGES:
        raise ValueError("max_pages must be between 1 and 50")

    try:
        from pypdf import PdfReader  # noqa: WPS433

        reader = PdfReader(io.BytesIO(payload))
        page_count = len(reader.pages)
    except Exception as exc:
        raise ValueError("invalid PDF document") from exc

    if page_count > max_pages:
        raise ValueError("PDF page count exceeds requested limit")

    pages: List[Dict[str, Any]] = []
    total_chars = 0
    truncated = False
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        remaining = max(0, MAX_PDF_TOTAL_CHARS - total_chars)
        allowed = min(MAX_PDF_PAGE_CHARS, remaining)
        if len(text) > allowed:
            text = text[:allowed]
            truncated = True
        total_chars += len(text)
        pages.append({
            "page_number": page_number,
            "text": text,
            "ocr_required": len(text.strip()) < ocr_min_chars,
        })
        if remaining == 0:
            truncated = True

    return pages, truncated


def extract_pdfs(
    pdf_paths: Sequence[PathLike],
    *,
    extracted_at: Optional[str] = None,
    ocr_fallback: bool = False,
    ocr_min_chars: int = 20,
) -> Dict[str, Any]:
    """Extract one or more PDFs into a full ``pages.json`` document."""
    all_pages: List[Dict[str, Any]] = []
    source_files: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    for raw in pdf_paths:
        path = Path(raw)
        if not path.is_file():
            errors[str(path)] = "file not found"
            continue
        pages, err = extract_pdf_pages(
            path, ocr_fallback=ocr_fallback, ocr_min_chars=ocr_min_chars,
        )
        if err:
            errors[path.name] = err
            continue
        try:
            sha = _sha256_file(path)
        except OSError as exc:
            sha = ""
            errors[path.name] = f"sha256 failed: {exc}"
        source_files.append({
            "path": str(path.resolve()),
            "file": path.name,
            "sha256": sha,
            "page_count": len(pages),
        })
        all_pages.extend(pages)

    doc = build_pages_document(
        all_pages,
        source_files=source_files,
        errors=errors,
        extracted_at=extracted_at,
    )
    if ocr_fallback:
        doc["ocr_fallback"] = True
        doc["ocr_min_chars"] = ocr_min_chars
    return doc


def parse_source_pages_txt(
    text_or_path: Union[str, PathLike],
) -> List[Dict[str, Any]]:
    """Parse PIFaudit-style ``source_pages.txt`` into page records."""
    if isinstance(text_or_path, (str, Path)) and Path(str(text_or_path)).is_file():
        text = Path(text_or_path).read_text(encoding="utf-8")
    else:
        text = str(text_or_path)

    pages: List[Dict[str, Any]] = []
    matches = list(_SOURCE_PAGES_HEADER.finditer(text))
    if not matches:
        return pages

    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip("\n")
        pages.append(normalize_page_record({
            "file": match.group("file").strip(),
            "page": int(match.group("page")),
            "text": body,
        }))
    return pages


def build_pages_document(
    pages: Sequence[Dict[str, Any]],
    *,
    source_files: Optional[Sequence[Dict[str, Any]]] = None,
    errors: Optional[Dict[str, str]] = None,
    extracted_at: Optional[str] = None,
    engine: str = "pypdf",
) -> Dict[str, Any]:
    """Wrap normalized pages in the canonical ``pages.json`` envelope."""
    from .. import __version__

    normalized = [normalize_page_record(p) for p in pages]
    return {
        "schema": PAGES_SCHEMA,
        "kernel_version": __version__,
        "engine": engine,
        "engine_version": _engine_version(),
        "extracted_at": extracted_at or _utc_now_iso(),
        "source_files": list(source_files or []),
        "errors": dict(errors or {}),
        "page_count": len(normalized),
        "pages": normalized,
    }


def load_pages_json(path: PathLike) -> Dict[str, Any]:
    """Load and lightly validate a ``pages.json`` file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != PAGES_SCHEMA:
        raise ValueError(f"unsupported schema: {data.get('schema')}")
    if "pages" not in data:
        raise ValueError("missing pages array")
    return data


def write_pages_json(doc: Dict[str, Any], path: PathLike) -> str:
    """Write ``pages.json``; returns output path string."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out)
