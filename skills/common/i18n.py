"""Shared i18n template (used by all skills).

Design principles
------------------
- The kernel engine outputs "language-neutral" structured results
  (code + params) rather than hardcoded language sentences.
- The skill's presentation layer uses `Catalog` to turn code/params into
  localized text based on `--lang`.
- Default language = en (targeting the international marketplace); switch
  with --lang zh-TW or an environment variable.

Usage
-----
    from skills.common.i18n import resolve_lang, Catalog
    lang = resolve_lang(args.lang)
    cat = Catalog(MESSAGES)
    print(cat.t("report.file", lang, path="a.docx"))
"""
from __future__ import annotations

import os
from typing import Dict, Optional

SUPPORTED = ("en", "zh-TW")
DEFAULT = "en"


def _normalize(value: str) -> Optional[str]:
    v = (value or "").strip().lower().replace("_", "-")
    if not v:
        return None
    if v.startswith("zh"):
        return "zh-TW"
    if v.startswith("en"):
        return "en"
    return None


def resolve_lang(arg: Optional[str] = None) -> str:
    """Determine the language: explicit arg > environment variable > default en."""
    norm = _normalize(arg) if arg else None
    if norm:
        return norm
    for var in ("PRODOCUX_LANG", "LC_ALL", "LANG"):
        norm = _normalize(os.environ.get(var, ""))
        if norm:
            return norm
    return DEFAULT


class Catalog:
    """Message catalog: key -> {lang -> template string}, params applied via str.format."""

    def __init__(self, messages: Dict[str, Dict[str, str]]):
        self._m = messages

    def t(self, msg_key: str, lang: str, **params) -> str:
        entry = self._m.get(msg_key, {})
        template = entry.get(lang) or entry.get(DEFAULT) or msg_key
        try:
            return template.format(**params)
        except (KeyError, IndexError, ValueError):
            return template


# Generic labels shared across skills (each skill may also bring its own catalog)
COMMON: Dict[str, Dict[str, str]] = {
    "label.file": {"en": "File", "zh-TW": "檔案"},
    "label.overall": {"en": "Overall", "zh-TW": "整體"},
    "label.suggestion": {"en": "Fix", "zh-TW": "建議"},
    "status.pass": {"en": "PASS", "zh-TW": "通過"},
    "status.fail": {"en": "FAIL", "zh-TW": "未通過"},
    "status.skip": {"en": "SKIP", "zh-TW": "略過"},
    "result.pass": {"en": "PASS \u2705", "zh-TW": "通過 \u2705"},
    "result.fail": {"en": "FAIL \u274c", "zh-TW": "未通過 \u274c"},
    "msg.no_files": {"en": "No matching files.", "zh-TW": "找不到符合的檔案。"},
    "sev.critical": {"en": "critical", "zh-TW": "嚴重"},
    "sev.high": {"en": "high", "zh-TW": "高"},
    "sev.medium": {"en": "medium", "zh-TW": "中"},
    "sev.low": {"en": "low", "zh-TW": "低"},
    "sev.none": {"en": "none", "zh-TW": "無"},
    "punc.colon": {"en": ": ", "zh-TW": "："},
}


def merge(*catalogs: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    """Merge multiple message catalogs (later ones override earlier ones)."""
    out: Dict[str, Dict[str, str]] = {}
    for c in catalogs:
        out.update(c)
    return out
