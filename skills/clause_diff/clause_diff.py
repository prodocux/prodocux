"""Skill #14: Multi-document Clause Diff — CLI + report.

Deterministic, no LLM. Aligns clauses across N .docx files by clause number
(第X條 / Article N / Section N / 1.2.3) and reports which clauses differ or
are missing in some versions.

This is the first i18n-native skill: kernel returns language-neutral data,
this layer localizes via skills.common.i18n (default English, --lang zh-TW).

Usage:
  python -m skills.clause_diff.clause_diff a.docx b.docx
  python -m skills.clause_diff.clause_diff a.docx b.docx c.docx --lang zh-TW
  python -m skills.clause_diff.clause_diff a.docx b.docx --json
  python -m skills.clause_diff.clause_diff a.docx b.docx --fail-on-diff
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
from prodocux_kernel.docdiff import clauses as cc  # noqa: E402
from skills.common.i18n import Catalog, resolve_lang  # noqa: E402

MESSAGES: Dict[str, Dict[str, str]] = {
    "title": {
        "en": "Clause comparison across {n} documents",
        "zh-TW": "{n} 份文件條款比對",
    },
    "documents": {"en": "Documents", "zh-TW": "文件"},
    "summary": {
        "en": "Same: {same}  Differs: {differs}  Missing in some: {missing}",
        "zh-TW": "相同 {same}、不同 {differs}、部分缺漏 {missing}",
    },
    "no_diff": {
        "en": "All clauses identical across versions.",
        "zh-TW": "所有條款在各版本一致。",
    },
    "clause": {"en": "Clause {key}", "zh-TW": "條款 {key}"},
    "status.differs": {"en": "DIFFERS", "zh-TW": "不同"},
    "status.missing_in_some": {"en": "MISSING in some", "zh-TW": "部分版本缺漏"},
    "absent": {"en": "(absent)", "zh-TW": "（無此條款）"},
}


def run(paths: List[str]) -> Dict[str, Any]:
    result = cc.compare_clauses(paths)
    result["kernel_version"] = __version__
    return result


def format_report(result: Dict[str, Any], lang: str) -> str:
    cat = Catalog(MESSAGES)
    s = result["summary"]
    lines: List[str] = []
    lines.append(cat.t("title", lang, n=len(result["documents"])))
    lines.append(cat.t("documents", lang) + ": " + ", ".join(result["documents"]))
    lines.append(cat.t("summary", lang, same=s["same"],
                       differs=s["differs"], missing=s["missing_in_some"]))
    lines.append("-" * 60)
    if not result["has_diff"]:
        lines.append(cat.t("no_diff", lang))
        return "\n".join(lines)
    for c in result["clauses"]:
        if c["status"] == "same":
            continue
        status = cat.t(f"status.{c['status']}", lang)
        lines.append(f"[{status}] " + cat.t("clause", lang, key=c["clause"]))
        for name, text in c["versions"].items():
            shown = text if text is not None else cat.t("absent", lang)
            shown = shown.replace("\n", " ")
            if len(shown) > 100:
                shown = shown[:100] + "…"
            lines.append(f"    {name}: {shown}")
        lines.append("")
    return "\n".join(lines).rstrip()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="ProDocuX Skill #14: Multi-document Clause Diff")
    ap.add_argument("paths", nargs="+", help="two or more .docx files")
    ap.add_argument("--lang", help="output language: en | zh-TW (default: en/locale)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--fail-on-diff", action="store_true",
                    help="exit non-zero if any clause differs/missing (CI gate)")
    args = ap.parse_args(argv)

    if len(args.paths) < 2:
        ap.error("need at least two .docx files to compare")

    lang = resolve_lang(args.lang)
    result = run(args.paths)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result, lang))

    if args.fail_on_diff and result["has_diff"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
