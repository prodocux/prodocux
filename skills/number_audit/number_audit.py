"""Skill #7: Number Consistency Audit — CLI + report.

Deterministic, no LLM. Checks:
  - table "total/subtotal" rows vs. the sum of the column above
  - amount-in-words vs. Arabic number consistency
  - mixed date formats across the document

i18n-native: kernel returns language-neutral code+params; this layer localizes.
Default output language: en. Override with --lang zh-TW or env PRODOCUX_LANG.

Usage:
  python -m skills.number_audit.number_audit invoice.docx
  python -m skills.number_audit.number_audit *.docx --lang zh-TW
  python -m skills.number_audit.number_audit a.docx --fail-on high
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
from prodocux_kernel.audit import numbers as na  # noqa: E402
from skills.common.i18n import COMMON, Catalog, merge, resolve_lang  # noqa: E402

_SEVERITY_RANK = {"high": 2, "medium": 1, "low": 0}

MESSAGES: Dict[str, Dict[str, str]] = {
    "na.overall": {
        "en": "{status} ({fail_count} issue(s), max severity: {sev})",
        "zh-TW": "{status}（發現 {fail_count} 個問題，最高嚴重度：{sev}）",
    },
    "na.no_issue": {"en": "No numeric inconsistencies found",
                    "zh-TW": "未發現數字不一致"},
    # ---- locations ----
    "loc.table_col": {"en": "Table {table}, column {col}", "zh-TW": "表 {table} 第 {col} 欄"},
    "loc.text": {"en": "{snippet}", "zh-TW": "{snippet}"},
    "loc.document": {"en": "whole document", "zh-TW": "整份文件"},
    # ---- finding details ----
    "table_total_mismatch": {
        "en": "Total row shows {total:g} but the column sum is {sum:g} (off by {diff:g})",
        "zh-TW": "合計列為 {total:g}，但上方加總為 {sum:g}（差 {diff:g}）",
    },
    "amount_words_mismatch": {
        "en": "Amount in words \"{words}\" = {words_value:g}, but the number = {number_value:g}",
        "zh-TW": "大寫「{words}」= {words_value:g}，數字 = {number_value:g} 不一致",
    },
    "date_format_inconsistent": {
        "en": "Multiple date formats detected: {styles}",
        "zh-TW": "偵測到多種日期格式：{styles}",
    },
    # ---- remediation ----
    "rem.table_total_mismatch": {
        "en": "Total does not match the line items; recheck the figures or recompute the total.",
        "zh-TW": "合計與明細加總不符，請核對該欄位數字或重算合計。",
    },
    "rem.amount_words_mismatch": {
        "en": "Amount in words disagrees with the digits; align both to the correct amount (common in contracts/invoices).",
        "zh-TW": "金額大寫與阿拉伯數字不一致，請以正確金額統一兩處（常見於合約/發票）。",
    },
    "rem.date_format_inconsistent": {
        "en": "The document mixes date formats; standardize to one (e.g. YYYY-MM-DD).",
        "zh-TW": "全文混用多種日期格式，建議統一為單一格式（如 YYYY-MM-DD）。",
    },
}

CAT = Catalog(merge(COMMON, MESSAGES))


def audit_file(path: str) -> Dict[str, Any]:
    result = na.audit_numbers(path)
    result["fail_count"] = len(result["findings"])
    result["max_severity"] = max(
        (f["severity"] for f in result["findings"]),
        key=lambda s: _SEVERITY_RANK[s], default="none",
    )
    return result


def format_report(report: Dict[str, Any], lang: str) -> str:
    lines: List[str] = []
    status = CAT.t("result.pass", lang) if report["passed"] else CAT.t("result.fail", lang)
    sev = CAT.t(f"sev.{report['max_severity']}", lang)
    colon = CAT.t("punc.colon", lang)
    lines.append(f"{CAT.t('label.file', lang)}{colon}{report['file']}")
    lines.append(f"{CAT.t('label.overall', lang)}{colon}" + CAT.t(
        "na.overall", lang, status=status, fail_count=report["fail_count"], sev=sev))
    lines.append("-" * 60)
    if not report["findings"]:
        lines.append(f"[{CAT.t('status.pass', lang)}] {CAT.t('na.no_issue', lang)}")
    for f in report["findings"]:
        loc = CAT.t(f["loc"], lang, **f["loc_params"])
        detail = CAT.t(f["check"], lang, **f["params"])
        sev_label = CAT.t(f"sev.{f['severity']}", lang)
        lines.append(f"[{CAT.t('status.fail', lang)}] {f['check']}  ({sev_label})  @ {loc}")
        lines.append(f"        {detail}")
        rem = CAT.t(f"rem.{f['check']}", lang)
        if rem != f"rem.{f['check']}":
            lines.append(f"        {CAT.t('label.suggestion', lang)}{colon}{rem}")
    return "\n".join(lines)


def run(paths: List[str], fail_on: Optional[str]) -> Dict[str, Any]:
    files: List[str] = []
    for p in paths:
        files.extend(glob.glob(p))
    if not files:
        return {"kernel_version": __version__, "reports": [], "ok": True}
    reports = [audit_file(f) for f in files]
    if fail_on:
        threshold = _SEVERITY_RANK[fail_on]
        ok = not any(
            _SEVERITY_RANK[f["severity"]] >= threshold
            for r in reports for f in r["findings"]
        )
    else:
        ok = all(r["passed"] for r in reports)
    return {"kernel_version": __version__, "reports": reports, "ok": ok}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="ProDocuX Skill #7: Number Consistency Audit")
    ap.add_argument("paths", nargs="+", help=".docx file(s) or globs")
    ap.add_argument("--lang", help="output language: en | zh-TW (default: en/locale)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--fail-on", choices=["medium", "high"],
                    help="exit non-zero at/above this severity (CI gate)")
    args = ap.parse_args(argv)

    lang = resolve_lang(args.lang)
    out = run(args.paths, args.fail_on)
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
