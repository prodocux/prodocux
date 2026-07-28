"""Skill #6: Document Structure Health Check — CLI + report.

Deterministic, no LLM. Checks common Word structural defects:
  - valid .docx
  - TOC is an automatic field (not hardcoded)
  - blank pages
  - broken cross-references
  - (with --reference) deleted section breaks, image-removal residue

i18n-native: kernel returns language-neutral code+params; this layer localizes.
Default output language: en. Override with --lang zh-TW or env PRODOCUX_LANG.

Usage:
  python -m skills.structure_health.health_check report.docx
  python -m skills.structure_health.health_check *.docx --reference original.docx
  python -m skills.structure_health.health_check a.docx --lang zh-TW
  python -m skills.structure_health.health_check a.docx --fail-on high   # CI gate
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
from prodocux_kernel.docops import invariants as inv  # noqa: E402
from prodocux_kernel.templating.mapping import MappingConfig  # noqa: E402
from skills.common.i18n import COMMON, Catalog, merge, resolve_lang  # noqa: E402

SEVERITY: Dict[str, str] = {
    "valid_docx": "critical",
    "toc_is_field": "high",
    "cross_references_valid": "high",
    "no_blank_pages": "medium",
    "no_orphan_section_break": "medium",
    "image_removal_no_residue": "medium",
    "heading_pagination_matches_policy": "medium",
    "pymupdf_available": "high",
    "evidence_render_complete": "high",
}

_SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}

MESSAGES: Dict[str, Dict[str, str]] = {
    "hc.overall": {
        "en": "{status} ({fail_count} failed, max severity: {sev})",
        "zh-TW": "{status}（失敗 {fail_count} 項，最高嚴重度：{sev}）",
    },
    # ---- invariant detail codes ----
    "valid_docx.ok": {"en": "File opens correctly", "zh-TW": "可正常開啟"},
    "valid_docx.cannot_open": {
        "en": "Cannot open as a valid .docx: {error}",
        "zh-TW": "無法開啟為合法 docx：{error}",
    },
    "toc_is_field.field": {"en": "TOC is a Word field", "zh-TW": "目錄為 TOC field"},
    "toc_is_field.hardcoded": {
        "en": "Looks like a hardcoded TOC (heading + page-number lines but no TOC field)",
        "zh-TW": "偵測到疑似硬寫入目錄（有目錄標題與頁碼行，但無 TOC field）",
    },
    "toc_is_field.none": {
        "en": "No TOC, or no hardcoding detected",
        "zh-TW": "無目錄或無硬寫入跡象",
    },
    "no_blank_pages.ok": {
        "en": "No blank pages detected (heuristic)",
        "zh-TW": "未偵測到空白頁（啟發式）",
    },
    "no_blank_pages.found": {
        "en": "Detected {n} suspected blank page(s) (heuristic)",
        "zh-TW": "偵測到 {n} 個疑似空白頁（啟發式）",
    },
    "cross_references_valid.ok": {
        "en": "Cross-references OK, or none present",
        "zh-TW": "交叉參照正常或無交叉參照",
    },
    "cross_references_valid.error_string": {
        "en": "Found broken-reference text: \"{text}\"",
        "zh-TW": "偵測到失效參照字串：「{text}」",
    },
    "cross_references_valid.broken": {
        "en": "{count} cross-reference(s) point to missing bookmarks: {sample}",
        "zh-TW": "有 {count} 個交叉參照指向不存在的書籤：{sample}",
    },
    "no_orphan_section_break.skipped_no_ref": {
        "en": "No reference provided", "zh-TW": "未提供 reference",
    },
    "no_orphan_section_break.ok": {
        "en": "Section count matches ({n})", "zh-TW": "section 數一致（{n}）",
    },
    "no_orphan_section_break.changed": {
        "en": "Section count changed: reference={ref} → target={target} (not authorized by spec)",
        "zh-TW": "section 數變動：reference={ref} → target={target}（未經 spec 授權）",
    },
    "image_removal_no_residue.skipped_no_ref": {
        "en": "No reference provided", "zh-TW": "未提供 reference",
    },
    "image_removal_no_residue.ok": {
        "en": "No image-removal residue", "zh-TW": "無刪圖殘餘空白頁",
    },
    "image_removal_no_residue.residue": {
        "en": "Images {img_b}→{img_a} but blank pages {blank_b}→{blank_a} (image removed, blank page left)",
        "zh-TW": "圖片由 {img_b} 減為 {img_a}，但空白頁由 {blank_b} 增為 {blank_a}（刪圖留殘餘空白頁）",
    },
    "heading_pagination_matches_policy.skipped_no_config": {
        "en": "No mapping pagination config (--config mapping.json)",
        "zh-TW": "未提供 mapping 分頁設定（請加 --config mapping.json）",
    },
    "heading_pagination_matches_policy.none_ok": {
        "en": "Pagination mode=none; no unexpected heading page breaks ({checked} headings)",
        "zh-TW": "分頁模式 none；標題未出現非預期換頁（{checked} 個標題）",
    },
    "heading_pagination_matches_policy.ok": {
        "en": "Heading page breaks match pagination policy ({checked} headings, mode={mode})",
        "zh-TW": "標題分頁符合 pagination 策略（{checked} 個標題，mode={mode}）",
    },
    "heading_pagination_matches_policy.mismatch": {
        "en": "{count} heading page-break mismatch(es) vs policy (mode={mode}): {sample}",
        "zh-TW": "有 {count} 個標題分頁不符合 pagination 策略（mode={mode}）：{sample}",
    },
    "heading_pagination_matches_policy.unexpected_breaks": {
        "en": "Pagination mode=none but {count} heading(s) still have page breaks: {sample}",
        "zh-TW": "分頁模式 none 但仍有 {count} 個標題帶換頁：{sample}",
    },
    "pymupdf_available.ok": {
        "en": "PyMuPDF/fitz available for PDF page render",
        "zh-TW": "PyMuPDF/fitz 可用，可渲染 PDF 頁面",
    },
    "pymupdf_available.missing": {
        "en": "PyMuPDF/fitz missing: {error}",
        "zh-TW": "缺少 PyMuPDF/fitz：{error}",
    },
    "pymupdf_available.skipped_optional": {
        "en": "PyMuPDF check skipped (optional without --require-pymupdf)",
        "zh-TW": "未強制檢查 PyMuPDF（未加 --require-pymupdf）",
    },
    "evidence_render_complete.skipped_no_index": {
        "en": "No evidence_index.json provided",
        "zh-TW": "未提供 evidence_index.json",
    },
    "evidence_render_complete.ok": {
        "en": "All render evidence images extracted ({render_count} render items)",
        "zh-TW": "render 證據圖已全部抽出（{render_count} 項）",
    },
    "evidence_render_complete.failed": {
        "en": "{count} render evidence item(s) failed: {sample}",
        "zh-TW": "有 {count} 項 render 證據圖抽取失敗：{sample}",
    },
    "skipped.valid_docx_failed": {
        "en": "Skipped (valid_docx failed)", "zh-TW": "valid_docx 失敗，略過",
    },
    "reference_load.error": {
        "en": "Cannot open reference: {error}", "zh-TW": "reference 無法開啟：{error}",
    },
    # ---- remediation (per invariant id) ----
    "rem.valid_docx": {
        "en": "File is corrupt or not .docx; verify the source file is intact.",
        "zh-TW": "檔案損毀或非 .docx；請確認來源檔案完整。",
    },
    "rem.toc_is_field": {
        "en": "TOC looks hardcoded. Use Word's automatic TOC (References → Table of Contents) so page numbers update automatically.",
        "zh-TW": "目錄疑似硬寫入。請改用 Word 自動目錄（參考資料→目錄），日後頁碼才會自動更新。",
    },
    "rem.no_blank_pages": {
        "en": "Blank pages detected, often leftover page breaks after deleting images/content. Remove extra page breaks or empty paragraphs.",
        "zh-TW": "偵測到空白頁，常因刪圖/刪內容後殘留分頁符。請刪除多餘的分頁符或空段落。",
    },
    "rem.cross_references_valid": {
        "en": "Broken cross-references. In Word select all and press F9 to update fields, or fix the target bookmark/heading.",
        "zh-TW": "有失效的交叉參照。請於 Word 全選後按 F9 更新功能變數，或修復指向的書籤/標題。",
    },
    "rem.no_orphan_section_break": {
        "en": "Section-break count differs from the source; a section break may have been deleted. Compare against the source to restore.",
        "zh-TW": "分節符數量與原始檔不一致，可能誤刪分節符。請比對原檔還原。",
    },
    "rem.image_removal_no_residue": {
        "en": "A blank page remains after removing an image. Also delete the empty paragraph/page break after the image.",
        "zh-TW": "刪除圖片後殘留空白頁。請一併刪除圖片後方的空段落/分頁符。",
    },
    "rem.heading_pagination_matches_policy": {
        "en": "Heading page breaks do not match template_rules.pagination. Re-run assemble with this repo's .venv Python.",
        "zh-TW": "標題分頁不符合 template_rules.pagination。請用本 repo `.venv` 的 Python 重跑 assemble。",
    },
    "rem.pymupdf_available": {
        "en": "Install pymupdf in the active runtime: pip install pymupdf. Prefer this repo's .venv Python (see runtime/INSTALL.md).",
        "zh-TW": "請在執行環境安裝 pymupdf；請改用本 repo `.venv` 的 Python（見 runtime/INSTALL.md）。",
    },
    "rem.evidence_render_complete": {
        "en": "Render evidence failed; fix PyMuPDF runtime then re-run doc_assemble --evidence.",
        "zh-TW": "render 證據圖失敗；修復 PyMuPDF 後重跑 doc_assemble --evidence。",
    },
}

CAT = Catalog(merge(COMMON, MESSAGES))


def check_file(
    path: str,
    reference: Optional[str] = None,
    *,
    config: Optional[MappingConfig] = None,
    evidence_index_path: Optional[str] = None,
    require_pymupdf: bool = False,
) -> Dict[str, Any]:
    evidence_index = None
    if evidence_index_path:
        try:
            evidence_index = json.loads(Path(evidence_index_path).read_text(encoding="utf-8"))
        except Exception:
            evidence_index = None
    results = inv.validate_structure(
        path,
        reference,
        heading_styles=config.heading_styles if config else None,
        pagination_policy=config.pagination if config else None,
        mapped_headings=[s.heading for s in config.sections] if config else None,
        evidence_index=evidence_index,
        require_pymupdf=require_pymupdf,
    )
    issues: List[Dict[str, Any]] = []
    for r in results:
        sev = SEVERITY.get(r.id, "low")
        issues.append({
            "id": r.id,
            "passed": r.passed,
            "status": r.status,
            "severity": sev,
            "code": r.code,
            "params": r.params,
        })
    failed = [i for i in issues if i["passed"] is False]
    return {
        "file": path,
        "passed": inv.overall_passed(results),
        "checks": issues,
        "fail_count": len(failed),
        "max_severity": max((i["severity"] for i in failed),
                            key=lambda s: _SEVERITY_RANK[s], default="none"),
    }


def format_report(report: Dict[str, Any], lang: str) -> str:
    lines: List[str] = []
    status = CAT.t("result.pass", lang) if report["passed"] else CAT.t("result.fail", lang)
    sev = CAT.t(f"sev.{report['max_severity']}", lang)
    colon = CAT.t("punc.colon", lang)
    lines.append(f"{CAT.t('label.file', lang)}{colon}{report['file']}")
    lines.append(f"{CAT.t('label.overall', lang)}{colon}" + CAT.t(
        "hc.overall", lang, status=status,
        fail_count=report["fail_count"], sev=sev))
    lines.append("-" * 60)
    for c in report["checks"]:
        detail = CAT.t(c["code"], lang, **c["params"])
        sev_label = CAT.t(f"sev.{c['severity']}", lang)
        if c["status"] == "skipped":
            lines.append(f"[{CAT.t('status.skip', lang)}] {c['id']}  — {detail}")
            continue
        tag = CAT.t("status.pass", lang) if c["passed"] else CAT.t("status.fail", lang)
        lines.append(f"[{tag}] {c['id']}  ({sev_label})")
        lines.append(f"        {detail}")
        if c["passed"] is False:
            rem = CAT.t(f"rem.{c['id']}", lang)
            if rem != f"rem.{c['id']}":
                lines.append(f"        {CAT.t('label.suggestion', lang)}{colon}{rem}")
    return "\n".join(lines)


def run(
    paths: List[str],
    reference: Optional[str],
    fail_on: Optional[str],
    *,
    config: Optional[MappingConfig] = None,
    evidence_index_path: Optional[str] = None,
    require_pymupdf: bool = False,
) -> Dict[str, Any]:
    files: List[str] = []
    for p in paths:
        files.extend(glob.glob(p))
    if not files:
        return {"kernel_version": __version__, "reports": [], "ok": True}

    reports = [
        check_file(
            f,
            reference,
            config=config,
            evidence_index_path=evidence_index_path,
            require_pymupdf=require_pymupdf,
        )
        for f in files
    ]
    ok = True
    if fail_on:
        threshold = _SEVERITY_RANK[fail_on]
        for r in reports:
            for c in r["checks"]:
                if c["passed"] is False and _SEVERITY_RANK[c["severity"]] >= threshold:
                    ok = False
    else:
        ok = all(r["passed"] for r in reports)
    return {"kernel_version": __version__, "reports": reports, "ok": ok}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="ProDocuX Skill #6: Document Structure Health Check")
    ap.add_argument("paths", nargs="+", help=".docx file(s) or globs")
    ap.add_argument("--reference", help="source/template file to enable comparison checks")
    ap.add_argument("--config", help="template_mapping.json for pagination policy checks")
    ap.add_argument("--evidence-index", help="evidence_index.json for render completeness check")
    ap.add_argument("--require-pymupdf", action="store_true",
                    help="fail if PyMuPDF/fitz is not importable")
    ap.add_argument("--lang", help="output language: en | zh-TW (default: en/locale)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--fail-on", choices=["medium", "high", "critical"],
                    help="exit non-zero at/above this severity (CI gate)")
    args = ap.parse_args(argv)

    lang = resolve_lang(args.lang)
    config = MappingConfig.from_json(args.config) if args.config else None
    out = run(
        args.paths,
        args.reference,
        args.fail_on,
        config=config,
        evidence_index_path=args.evidence_index,
        require_pymupdf=args.require_pymupdf,
    )
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if not out["reports"]:
            print(CAT.t("msg.no_files", lang))
        for r in out["reports"]:
            print(format_report(r, lang))
            print()
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
