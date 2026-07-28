"""Skill #9: Taiwan PIF Compliance Audit — CLI + report.

Deterministic, no LLM. Audits a Taiwan cosmetics Product Information File (PIF)
against TFDA Article 3 (16 mandatory sections) plus structural gate checks.

Legal basis: 化粧品產品資訊檔案管理辦法 第3條 + 製作指引。

i18n-native: kernel returns language-neutral code+params; this layer localizes.
Default output language: en. Override with --lang zh-TW or env PRODOCUX_LANG.

Usage:
  python -m skills.pif_audit.pif_audit pif.docx
  python -m skills.pif_audit.pif_audit pif.docx --lang zh-TW
  python -m skills.pif_audit.pif_audit pif.docx --config checklist.json --mapping mapping.json
  python -m skills.pif_audit.pif_audit pif.docx --fail-on high
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
from prodocux_kernel.audit import pif_tw  # noqa: E402
from prodocux_kernel.templating.mapping import MappingConfig  # noqa: E402
from skills.common.i18n import COMMON, Catalog, merge, resolve_lang  # noqa: E402

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "pif_tw"
_DEFAULT_CHECKLIST = _EXAMPLES / "tw_pif_checklist.json"
_DEFAULT_MAPPING = _EXAMPLES / "template_mapping.json"

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "none": 0}

MESSAGES: Dict[str, Dict[str, str]] = {
    "pif.overall": {
        "en": "{status} ({fail_count} issue(s), max severity: {sev}; sections {found}/{required})",
        "zh-TW": "{status}（發現 {fail_count} 個問題，最高嚴重度：{sev}；區段 {found}/{required}）",
    },
    "pif.regulation": {
        "en": "Regulation: {name} ({agency})",
        "zh-TW": "法規依據：{name}（{agency}）",
    },
    "pif.no_issue": {
        "en": "All mandatory PIF sections present with substantive content",
        "zh-TW": "16 項必要區段皆存在且具實質內容",
    },
    # ---- locations ----
    "loc.section": {"en": "Section {id}: {title}", "zh-TW": "區段 {id}：{title}"},
    "loc.document": {"en": "whole document", "zh-TW": "整份文件"},
    # ---- findings ----
    "section_missing": {
        "en": "Mandatory section missing from document: {title}",
        "zh-TW": "缺少必要區段：{title}",
    },
    "section_empty_or_placeholder": {
        "en": "Section \"{title}\" is empty or still a placeholder ({chars} chars)",
        "zh-TW": "區段「{title}」為空或仍為佔位內容（{chars} 字）",
    },
    "section_keywords_missing": {
        "en": "Section \"{title}\" lacks expected keywords (e.g. {sample})",
        "zh-TW": "區段「{title}」未見預期關鍵字（如 {sample}）",
    },
    "section_required_keyword_missing": {
        "en": "Section \"{title}\" missing required keyword: {keyword}",
        "zh-TW": "區段「{title}」缺少必要關鍵字：{keyword}",
    },
    "review_marker_in_section": {
        "en": "Section \"{title}\" contains review marker \"{marker}\" — needs human confirmation",
        "zh-TW": "區段「{title}」含待確認標記「{marker}」",
    },
    "safety_subrequirement_missing": {
        "en": "Section 16 missing sub-requirement: {sub_id} (safety conclusion or SA qualification)",
        "zh-TW": "第 16 項缺少子要件：{sub_id}（安全評估結論或簽署人員資格）",
    },
    # structure.* reuse codes from #6
    "structure.valid_docx": {
        "en": "Cannot open as valid .docx",
        "zh-TW": "無法開啟為合法 docx",
    },
    "structure.toc_is_field": {
        "en": "TOC is not a Word field (may be hardcoded)",
        "zh-TW": "目錄非 TOC field（可能為硬寫入）",
    },
    "structure.no_blank_pages": {
        "en": "Suspected blank page(s) detected",
        "zh-TW": "偵測到疑似空白頁",
    },
    "structure.cross_references_valid": {
        "en": "Broken cross-references in document",
        "zh-TW": "文件含失效交叉參照",
    },
    # ---- remediation ----
    "rem.section_missing": {
        "en": "Add the missing section per TFDA Article 3; use the PIF template heading structure.",
        "zh-TW": "依衛福部辦法第 3 條補齊缺少區段；對照 PIF 模板標題結構。",
    },
    "rem.section_empty_or_placeholder": {
        "en": "Replace placeholder text with source-backed content before submission.",
        "zh-TW": "將佔位內容替換為有來源依據的實質資料後再送審。",
    },
    "rem.section_keywords_missing": {
        "en": "Section content may be incomplete; verify against the regulation checklist.",
        "zh-TW": "區段內容可能不完整，請對照法規檢核表確認。",
    },
    "rem.section_required_keyword_missing": {
        "en": "This section has a mandatory element (e.g. INCI names, safety assessment) — add it.",
        "zh-TW": "此區段有強制要素（如 INCI 名稱、安全評估）— 請補上。",
    },
    "rem.review_marker_in_section": {
        "en": "Resolve flagged items or document why they are acceptable before final delivery.",
        "zh-TW": "處理標記項目，或說明可接受理由後再正式交付。",
    },
    "rem.safety_subrequirement_missing": {
        "en": "Section 16 must include both the signed safety conclusion AND the SA qualification proof (Art. 3(16)).",
        "zh-TW": "第 16 項須同時包含簽署之安全評估結論與安全資料簽署人員資格證明（辦法第 3 條第 16 款）。",
    },
    "rem.structure.toc_is_field": {
        "en": "Regenerate TOC as a Word field so page numbers update automatically.",
        "zh-TW": "請以 Word TOC field 重生目錄，頁碼才會自動更新。",
    },
    "rem.structure.no_blank_pages": {
        "en": "Remove extra page breaks or empty paragraphs (common after image deletion).",
        "zh-TW": "移除多餘分頁符或空段落（刪圖後常見）。",
    },
    "rem.structure.cross_references_valid": {
        "en": "Update fields (F9) or fix broken bookmarks from stale TOC.",
        "zh-TW": "更新功能變數（F9）或修復舊目錄造成的失效書籤。",
    },
}

CAT = Catalog(merge(COMMON, MESSAGES))


def _loc_text(finding: Dict[str, Any], lang: str) -> str:
    return CAT.t(finding.get("loc", "loc.document"), lang, **finding.get("loc_params", {}))


def audit_file(
    path: str,
    checklist_path: Optional[str] = None,
    mapping_path: Optional[str] = None,
) -> Dict[str, Any]:
    checklist = pif_tw.load_checklist(checklist_path or _DEFAULT_CHECKLIST)
    mapping = MappingConfig.from_json(mapping_path or _DEFAULT_MAPPING)
    return pif_tw.audit_pif_tw(path, mapping, checklist)


def format_report(report: Dict[str, Any], lang: str) -> str:
    colon = CAT.t("punc.colon", lang)
    lines: List[str] = []
    status = CAT.t("result.pass", lang) if report["passed"] else CAT.t("result.fail", lang)
    sev = CAT.t(f"sev.{report['max_severity']}", lang)
    reg = report.get("regulation", {})
    if reg:
        lines.append(CAT.t("pif.regulation", lang,
                           name=reg.get("name", reg.get("regulation", "")),
                           agency=reg.get("agency", "")))
    lines.append(f"{CAT.t('label.file', lang)}{colon}{report['file']}")
    lines.append(f"{CAT.t('label.overall', lang)}{colon}" + CAT.t(
        "pif.overall", lang, status=status, fail_count=report["fail_count"],
        sev=sev, found=report["sections_found"], required=report["sections_required"]))
    if report["passed"]:
        lines.append(CAT.t("pif.no_issue", lang))
    lines.append("-" * 60)
    for f in report["findings"]:
        detail = CAT.t(f["check"], lang, **f.get("params", {}))
        sev_label = CAT.t(f"sev.{f['severity']}", lang)
        loc = _loc_text(f, lang)
        lines.append(f"[{CAT.t('status.fail', lang)}] {f['check']}  ({sev_label})")
        lines.append(f"        {loc}")
        lines.append(f"        {detail}")
        rem_key = f"rem.{f['check']}"
        rem = CAT.t(rem_key, lang)
        if rem != rem_key:
            lines.append(f"        {CAT.t('label.suggestion', lang)}{colon}{rem}")
    return "\n".join(lines)


def run(paths: List[str], checklist: Optional[str], mapping: Optional[str],
        fail_on: Optional[str]) -> Dict[str, Any]:
    files: List[str] = []
    for p in paths:
        files.extend(glob.glob(p))
    if not files:
        return {"kernel_version": __version__, "reports": [], "ok": True}

    reports = [audit_file(f, checklist, mapping) for f in files]
    ok = True
    if fail_on:
        threshold = _SEVERITY_RANK[fail_on]
        for r in reports:
            for f in r["findings"]:
                if _SEVERITY_RANK[f["severity"]] >= threshold:
                    ok = False
    else:
        ok = all(r["passed"] for r in reports)
    return {"kernel_version": __version__, "reports": reports, "ok": ok}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="ProDocuX Skill #9: Taiwan PIF Compliance Audit")
    ap.add_argument("paths", nargs="+", help=".docx PIF file(s) or globs")
    ap.add_argument("--config", help=f"checklist JSON (default: {_DEFAULT_CHECKLIST})")
    ap.add_argument("--mapping", help=f"template mapping JSON (default: {_DEFAULT_MAPPING})")
    ap.add_argument("--lang", help="output language: en | zh-TW (default: en/locale)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--fail-on", choices=["medium", "high", "critical"],
                    help="exit non-zero at/above this severity (CI gate)")
    args = ap.parse_args(argv)

    lang = resolve_lang(args.lang)
    out = run(args.paths, args.config, args.mapping, args.fail_on)
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
