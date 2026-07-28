"""Skill: Template Document Assembler — CLI + report.

Fills a user-specified .docx template by heading-anchored section replacement,
applies deterministic structure polish (page-break cleanup, table fit, page-number
footer, TOC field, review highlights), then runs the L0 structural gate (#6).

Deterministic, **no LLM at runtime**. Section content (`drafts`) is produced upstream
(by a solver/LLM) and passed in as language-neutral text via a JSON file.

i18n-native: kernel returns language-neutral code+params; this layer localizes.
Default output language: en. Override with --lang zh-TW or env PRODOCUX_LANG.

Usage:
  python -m skills.doc_assemble.assemble template.docx \
      --config mapping.json --drafts drafts.json --output out.docx
  ... --toc-after 目錄 --toc-until 產品敘述 --footer-style zh --review-term 待補充
  ... --lang zh-TW --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prodocux_kernel import __version__  # noqa: E402
from prodocux_kernel.templating import pipeline, render  # noqa: E402
from prodocux_kernel.templating.mapping import MappingConfig, validate_config  # noqa: E402
from skills.common.i18n import COMMON, Catalog, merge, resolve_lang  # noqa: E402
from skills.structure_health.health_check import MESSAGES as HC_MESSAGES  # noqa: E402
from skills.structure_health.health_check import SEVERITY  # noqa: E402

MESSAGES: Dict[str, Dict[str, str]] = {
    "asm.title": {"en": "Assembled document", "zh-TW": "已組裝文件"},
    "asm.ops": {"en": "Operations", "zh-TW": "處理動作"},
    "asm.sections_written": {"en": "Sections written", "zh-TW": "寫入區段"},
    "asm.tables_written": {"en": "Tables written", "zh-TW": "寫入表格"},
    "asm.front_matter_written": {"en": "Front matter fields written", "zh-TW": "封面欄位寫入"},
    "asm.blank_removed": {"en": "Blank page-breaks removed", "zh-TW": "移除空白分頁"},
    "asm.headings_paged": {"en": "Headings paged", "zh-TW": "標題分頁"},
    "asm.tables_fitted": {"en": "Tables fitted to page", "zh-TW": "表格縮頁"},
    "asm.toc_inserted": {"en": "TOC field inserted", "zh-TW": "插入 TOC field"},
    "asm.review_marked": {"en": "Review marks", "zh-TW": "待確認標記"},
    "asm.gate": {"en": "L0 structural gate", "zh-TW": "L0 結構閘門"},
    "asm.yes": {"en": "yes", "zh-TW": "是"},
    "asm.no": {"en": "no", "zh-TW": "否"},
    "asm.no_drafts": {
        "en": "No drafts provided; nothing to write.",
        "zh-TW": "未提供草稿，無內容可寫入。",
    },
    "asm.config_invalid": {
        "en": "Mapping config invalid: {issues}",
        "zh-TW": "映射設定不合法：{issues}",
    },
    "asm.missing_sections": {
        "en": "Warning: draft section id(s) not in config: {ids}",
        "zh-TW": "警告：草稿中的 section id 不在設定內：{ids}",
    },
    "asm.pipeline": {"en": "Flagship pipeline", "zh-TW": "旗艦管線"},
    "asm.pages": {"en": "Pages extracted", "zh-TW": "抽文頁數"},
    "asm.source_map": {"en": "Source map", "zh-TW": "來源映射"},
    "asm.evidence": {"en": "Evidence images applied", "zh-TW": "證據圖注入"},
}

_PIPELINE_RESULT: Optional[pipeline.PipelineResult] = None

CAT = Catalog(merge(COMMON, HC_MESSAGES, MESSAGES))

_FOOTER_PRESETS = {
    "en": render.FooterSpec(prefix="Page ", middle=" of ", suffix=""),
    "zh": render.FooterSpec(prefix="第 ", middle=" 頁 / 共 ", suffix=" 頁"),
}


def assemble(
    template: str,
    config: MappingConfig,
    drafts: Dict[str, Any],
    output: str,
    *,
    toc_after: Optional[str] = None,
    toc_until: Optional[str] = None,
    footer_style: Optional[str] = None,
    review_terms: Optional[List[str]] = None,
    validate: bool = True,
    pdf_paths: Optional[List[str]] = None,
    pages_json: Optional[str] = None,
    pages_out: Optional[str] = None,
    source_map_out: Optional[str] = None,
    evidence_spec: Optional[str] = None,
    evidence_pdf: Optional[str] = None,
    evidence_index_out: Optional[str] = None,
    image_dir: Optional[str] = None,
    ocr_fallback: bool = False,
    ocr_min_chars: int = 20,
) -> render.RenderResult:
    global _PIPELINE_RESULT
    toc = render.TocSpec(after_heading=toc_after, until_heading=toc_until) if toc_after else None
    footer = _FOOTER_PRESETS.get(footer_style) if footer_style else None
    use_pipeline = bool(pdf_paths or pages_json or evidence_spec)
    if use_pipeline:
        pr = pipeline.run_flagship_pipeline(
            template, output, config, drafts,
            pdf_paths=pdf_paths,
            pages_json=pages_json,
            pages_out=pages_out,
            source_map_out=source_map_out,
            evidence_spec=evidence_spec,
            evidence_pdf=evidence_pdf,
            evidence_index_out=evidence_index_out,
            image_dir=image_dir,
            ocr_fallback=ocr_fallback,
            ocr_min_chars=ocr_min_chars,
            toc=toc,
            footer=footer,
            review_terms=review_terms,
            validate=validate,
        )
        _PIPELINE_RESULT = pr
        return pr.render
    _PIPELINE_RESULT = None
    return render.render_document(
        template, output, drafts, config,
        toc=toc, footer=footer, review_terms=review_terms, validate=validate,
    )


def last_pipeline_result() -> Optional[pipeline.PipelineResult]:
    return _PIPELINE_RESULT


def format_report(result: render.RenderResult, lang: str) -> str:
    colon = CAT.t("punc.colon", lang)
    lines: List[str] = []
    pr = last_pipeline_result()
    lines.append(f"{CAT.t('asm.title', lang)}{colon}{result.output_path}")
    status = CAT.t("result.pass", lang) if result.passed else CAT.t("result.fail", lang)
    lines.append(f"{CAT.t('label.overall', lang)}{colon}{status}")
    if pr and (pr.pages_document or pr.source_map or pr.evidence_injection):
        lines.append(CAT.t("asm.pipeline", lang) + colon)
        if pr.pages_document:
            lines.append(f"  {CAT.t('asm.pages', lang)}{colon}{pr.pages_document.get('page_count', 0)}")
            if pr.pages_path:
                lines.append(f"  pages.json → {pr.pages_path}")
        if pr.source_map_path:
            lines.append(f"  {CAT.t('asm.source_map', lang)}{colon}{pr.source_map_path}")
        if pr.evidence_injection is not None:
            lines.append(
                f"  {CAT.t('asm.evidence', lang)}{colon}{pr.evidence_injection.get('applied', 0)}"
                f" ({pr.evidence_injection.get('skipped', 0)} skipped)"
            )
            if pr.evidence_index_path:
                lines.append(f"  evidence_index.json → {pr.evidence_index_path}")
    lines.append("-" * 60)
    lines.append(CAT.t("asm.ops", lang) + colon)
    yes, no = CAT.t("asm.yes", lang), CAT.t("asm.no", lang)
    lines.append(f"  {CAT.t('asm.sections_written', lang)}{colon}{result.sections_written}")
    lines.append(f"  {CAT.t('asm.tables_written', lang)}{colon}{result.tables_written}")
    lines.append(f"  {CAT.t('asm.front_matter_written', lang)}{colon}{result.front_matter_written}")
    lines.append(f"  {CAT.t('asm.blank_removed', lang)}{colon}{result.blank_breaks_removed}")
    lines.append(f"  {CAT.t('asm.headings_paged', lang)}{colon}{result.headings_paged}")
    lines.append(f"  {CAT.t('asm.tables_fitted', lang)}{colon}{result.tables_fitted}")
    lines.append(f"  {CAT.t('asm.toc_inserted', lang)}{colon}{yes if result.toc_inserted else no}")
    lines.append(f"  {CAT.t('asm.review_marked', lang)}{colon}{result.review_marked}")
    if result.invariants:
        lines.append(CAT.t("asm.gate", lang) + colon)
        for inv in result.invariants:
            detail = CAT.t(inv.code, lang, **inv.params)
            if inv.status == "skipped":
                lines.append(f"  [{CAT.t('status.skip', lang)}] {inv.id}  — {detail}")
                continue
            tag = CAT.t("status.pass", lang) if inv.passed else CAT.t("status.fail", lang)
            sev = CAT.t(f"sev.{SEVERITY.get(inv.id, 'low')}", lang)
            lines.append(f"  [{tag}] {inv.id}  ({sev})")
            lines.append(f"        {detail}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="ProDocuX Skill: Template Document Assembler")
    ap.add_argument("template", help="user-specified .docx template")
    ap.add_argument("--config", required=True, help="mapping config JSON")
    ap.add_argument("--drafts", required=True, help="drafts JSON: {section_id: [lines]}")
    ap.add_argument("--output", required=True, help="output .docx path")
    ap.add_argument("--toc-after", help="heading after which to (re)insert the TOC field")
    ap.add_argument("--toc-until", help="heading until which to clear old TOC content")
    ap.add_argument("--footer-style", choices=["en", "zh"], help="page-number footer preset")
    ap.add_argument("--review-term", action="append", default=[],
                    help="term to highlight for human review (repeatable)")
    ap.add_argument("--no-validate", action="store_true", help="skip the L0 gate")
    ap.add_argument("--pdfs", nargs="+", metavar="PDF", help="source PDF(s) for page extraction")
    ap.add_argument("--pages", help="pre-built pages.json (skip PDF extraction)")
    ap.add_argument("--pages-out", help="write extracted pages.json here")
    ap.add_argument("--source-map-out", help="write source_map.json here")
    ap.add_argument("--evidence", help="evidence_spec.json for PDF evidence image injection")
    ap.add_argument("--evidence-pdf", help="PDF for evidence extraction (default: first --pdfs)")
    ap.add_argument("--evidence-index-out", help="write evidence_index.json here")
    ap.add_argument("--image-dir", help="directory for extracted evidence images")
    ap.add_argument("--ocr", action="store_true",
                    help="OCR fallback when page text is sparse (needs tesseract + pytesseract)")
    ap.add_argument("--ocr-min-chars", type=int, default=20, help="OCR when chars below this (default: 20)")
    ap.add_argument("--lang", help="output language: en | zh-TW (default: en/locale)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args(argv)

    lang = resolve_lang(args.lang)
    config = MappingConfig.from_json(args.config)
    issues = validate_config(config)
    if issues:
        print(CAT.t("asm.config_invalid", lang, issues="; ".join(issues)), file=sys.stderr)
        return 2

    drafts = json.loads(Path(args.drafts).read_text(encoding="utf-8"))
    if not drafts:
        print(CAT.t("asm.no_drafts", lang), file=sys.stderr)
        return 2
    known = {s.id for s in config.sections} | {"front_matter"}
    unknown = [k for k in drafts if k not in known]
    if unknown:
        print(CAT.t("asm.missing_sections", lang, ids=", ".join(unknown)), file=sys.stderr)

    result = assemble(
        args.template, config, drafts, args.output,
        toc_after=args.toc_after, toc_until=args.toc_until,
        footer_style=args.footer_style, review_terms=args.review_term or None,
        validate=not args.no_validate,
        pdf_paths=args.pdfs,
        pages_json=args.pages,
        pages_out=args.pages_out,
        source_map_out=args.source_map_out,
        evidence_spec=args.evidence,
        evidence_pdf=args.evidence_pdf,
        evidence_index_out=args.evidence_index_out,
        image_dir=args.image_dir,
        ocr_fallback=args.ocr,
        ocr_min_chars=args.ocr_min_chars,
    )
    pr = last_pipeline_result()

    if args.json:
        payload: Dict[str, Any] = {
            "kernel_version": __version__,
            "output": result.output_path,
            "passed": pr.passed if pr else result.passed,
            "sections_written": result.sections_written,
            "tables_written": result.tables_written,
            "front_matter_written": result.front_matter_written,
            "blank_breaks_removed": result.blank_breaks_removed,
            "headings_paged": result.headings_paged,
            "tables_fitted": result.tables_fitted,
            "toc_inserted": result.toc_inserted,
            "review_marked": result.review_marked,
            "invariants": result.invariant_summary,
        }
        if pr:
            payload["pipeline"] = pr.to_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_report(result, lang))

    ok = pr.passed if pr else result.passed
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
