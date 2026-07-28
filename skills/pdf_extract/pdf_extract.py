"""CR-001: PDF page text extraction — CLI + pages.json output.

Deterministic input-prep. No LLM. Uses pypdf to extract per-page text with
stable {file, page, text} records for map_sources_to_sections and provenance.

Also supports importing PIFaudit-style source_pages.txt as a dev bridge.

Usage:
  python -m skills.pdf_extract.pdf_extract report.pdf --out pages.json
  python -m skills.pdf_extract.pdf_extract *.pdf --out pages.json
  python -m skills.pdf_extract.pdf_extract --from-source-pages source_pages.txt --out pages.json
  python -m skills.pdf_extract.pdf_extract report.pdf --lang zh-TW --json
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prodocux_kernel import __version__  # noqa: E402
from prodocux_kernel.intake import pdf as intake  # noqa: E402
from skills.common.i18n import COMMON, Catalog, merge, resolve_lang  # noqa: E402

MESSAGES: Dict[str, Dict[str, str]] = {
    "px.summary": {
        "en": "{status} — {page_count} page(s) from {file_count} file(s)",
        "zh-TW": "{status} — 共 {page_count} 頁，來自 {file_count} 個檔案",
    },
    "px.output": {
        "en": "Wrote {path}",
        "zh-TW": "已寫入 {path}",
    },
    "px.errors": {
        "en": "{count} file error(s): {sample}",
        "zh-TW": "{count} 個檔案錯誤：{sample}",
    },
    "px.no_input": {
        "en": "Provide PDF path(s) or --from-source-pages",
        "zh-TW": "請提供 PDF 路徑，或使用 --from-source-pages",
    },
    "px.page_line": {
        "en": "  p.{page}  ({chars} chars)  {file}",
        "zh-TW": "  第 {page} 頁（{chars} 字）  {file}",
    },
}

CAT = Catalog(merge(COMMON, MESSAGES))


def extract_from_pdfs(
    paths: List[str],
    *,
    ocr_fallback: bool = False,
    ocr_min_chars: int = 20,
) -> Dict[str, Any]:
    files: List[str] = []
    for p in paths:
        files.extend(glob.glob(p))
    files = sorted(set(files))
    if not files:
        return {
            "kernel_version": __version__,
            "ok": False,
            "document": intake.build_pages_document([], errors={"input": "no files matched"}),
            "output_path": None,
        }
    doc = intake.extract_pdfs(
        files, ocr_fallback=ocr_fallback, ocr_min_chars=ocr_min_chars,
    )
    ok = not doc["errors"] and doc["page_count"] > 0
    return {
        "kernel_version": __version__,
        "ok": ok,
        "document": doc,
        "output_path": None,
    }


def extract_from_source_pages(path: str) -> Dict[str, Any]:
    pages = intake.parse_source_pages_txt(path)
    doc = intake.build_pages_document(
        pages,
        source_files=[{"path": str(Path(path).resolve()), "file": Path(path).name,
                       "sha256": "", "page_count": len(pages)}],
        engine="source_pages_txt",
    )
    return {
        "kernel_version": __version__,
        "ok": len(pages) > 0,
        "document": doc,
        "output_path": None,
    }


def format_report(result: Dict[str, Any], lang: str) -> str:
    doc = result["document"]
    colon = CAT.t("punc.colon", lang)
    status = CAT.t("result.pass", lang) if result["ok"] else CAT.t("result.fail", lang)
    file_count = len(doc.get("source_files", []))
    lines = [
        CAT.t("px.summary", lang,
              status=status, page_count=doc.get("page_count", 0), file_count=file_count),
        f"{CAT.t('label.file', lang)}{colon}{doc.get('engine', '?')} "
        f"v{doc.get('engine_version', '?')}  schema={doc.get('schema', '?')}",
    ]
    if doc.get("errors"):
        sample = "; ".join(f"{k}: {v}" for k, v in list(doc["errors"].items())[:3])
        lines.append(CAT.t("px.errors", lang, count=len(doc["errors"]), sample=sample))
    if result.get("output_path"):
        lines.append(CAT.t("px.output", lang, path=result["output_path"]))
    lines.append("-" * 60)
    for page in doc.get("pages", [])[:20]:
        lines.append(CAT.t(
            "px.page_line", lang,
            page=page["page"], chars=page.get("char_count", len(page.get("text", ""))),
            file=page["file"],
        ))
    extra = doc.get("page_count", 0) - 20
    if extra > 0:
        lines.append(f"  ... +{extra} more page(s)")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="ProDocuX CR-001: PDF page text extraction (deterministic)")
    ap.add_argument("paths", nargs="*", help="PDF file(s) or globs")
    ap.add_argument("--out", "-o", help="write pages.json to this path")
    ap.add_argument("--from-source-pages", metavar="TXT",
                    help="import PIFaudit-style source_pages.txt instead of PDF")
    ap.add_argument("--ocr", action="store_true",
                    help="OCR fallback for sparse pages (needs tesseract + pytesseract)")
    ap.add_argument("--ocr-min-chars", type=int, default=20)
    ap.add_argument("--lang", help="output language: en | zh-TW")
    ap.add_argument("--json", action="store_true", help="emit JSON to stdout")
    args = ap.parse_args(argv)

    lang = resolve_lang(args.lang)
    if args.from_source_pages:
        result = extract_from_source_pages(args.from_source_pages)
    elif args.paths:
        result = extract_from_pdfs(
            args.paths, ocr_fallback=args.ocr, ocr_min_chars=args.ocr_min_chars,
        )
    else:
        print(CAT.t("px.no_input", lang), file=sys.stderr)
        return 2

    if args.out:
        out_path = intake.write_pages_json(result["document"], args.out)
        result["output_path"] = out_path

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result, lang))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
