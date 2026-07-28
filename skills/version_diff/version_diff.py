"""Skill #15: Document Version Diff (red-line) — CLI + report.

Deterministic, no LLM. Compares two .docx files and reports paragraph/table
level added/removed/modified blocks.

i18n: kernel returns language-neutral data; this layer localizes.
Default output language: en. Override with --lang zh-TW or env PRODOCUX_LANG.

Usage:
  python -m skills.version_diff.version_diff old.docx new.docx
  python -m skills.version_diff.version_diff old.docx new.docx --lang zh-TW
  python -m skills.version_diff.version_diff old.docx new.docx --json
  python -m skills.version_diff.version_diff old.docx new.docx --fail-on-change
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
from prodocux_kernel.docdiff import compare as dc  # noqa: E402
from skills.common.i18n import Catalog, resolve_lang  # noqa: E402

MESSAGES: Dict[str, Dict[str, str]] = {
    "vd.old": {"en": "Old: {path}", "zh-TW": "舊版：{path}"},
    "vd.new": {"en": "New: {path}", "zh-TW": "新版：{path}"},
    "vd.summary": {
        "en": "Changes — added {added}, removed {removed}, modified {replaced}",
        "zh-TW": "變更：新增 {added}、刪除 {removed}、修改 {replaced}",
    },
    "vd.no_change": {"en": " (no differences)", "zh-TW": "（無差異）"},
}

CAT = Catalog(MESSAGES)


def format_report(result: Dict[str, Any], lang: str) -> str:
    lines: List[str] = []
    s = result["summary"]
    lines.append(CAT.t("vd.old", lang, path=result["old"]))
    lines.append(CAT.t("vd.new", lang, path=result["new"]))
    summary = CAT.t("vd.summary", lang, added=s["added"],
                    removed=s["removed"], replaced=s["replaced"])
    if not result["changed"]:
        summary += CAT.t("vd.no_change", lang)
    lines.append(summary)
    lines.append("-" * 60)
    for ch in result["changes"]:
        if ch["type"] == "added":
            for t in ch["new"]:
                lines.append(f"+ {t}")
        elif ch["type"] == "removed":
            for t in ch["old"]:
                lines.append(f"- {t}")
        else:  # replaced
            for t in ch["old"]:
                lines.append(f"- {t}")
            for t in ch["new"]:
                lines.append(f"+ {t}")
        lines.append("")
    return "\n".join(lines).rstrip()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="ProDocuX Skill #15: Document Version Diff (red-line)")
    ap.add_argument("old", help="old .docx")
    ap.add_argument("new", help="new .docx")
    ap.add_argument("--lang", help="output language: en | zh-TW (default: en/locale)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--fail-on-change", action="store_true",
                    help="exit non-zero on any difference (CI gate)")
    args = ap.parse_args(argv)

    lang = resolve_lang(args.lang)
    result = dc.compare_docx(args.old, args.new)
    result["kernel_version"] = __version__

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result, lang))

    if args.fail_on_change and result["changed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
