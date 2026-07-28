"""#14 Multi-document contract clause diff engine (deterministic, no LLM calls).

Aligns clauses across N documents by clause number and outputs a
language-neutral structured comparison result:
status ∈ {same, differs, missing_in_some}. Localization is the presentation
layer's responsibility.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

from docx import Document

# Clause-heading detection: 第X條 / Article N / Section N / 1. / 1.2.3) etc.
_CLAUSE_PATTERNS = [
    re.compile(r"^\s*(第\s*[一二三四五六七八九十百千零兩\d]+\s*條)"),
    re.compile(r"^\s*(Article\s+\d+)", re.I),
    re.compile(r"^\s*(Section\s+\d+)", re.I),
    re.compile(r"^\s*(\d+(?:\.\d+)*)[\.\)、]"),
]


def _clause_key(text: str) -> Optional[str]:
    for pat in _CLAUSE_PATTERNS:
        m = pat.match(text)
        if m:
            return re.sub(r"\s+", "", m.group(1))
    return None


def extract_clauses(path: str) -> Tuple[Dict[str, str], List[str]]:
    """Return (clauses{key->text}, list of keys in order of appearance)."""
    doc = Document(path)
    clauses: Dict[str, str] = {}
    order: List[str] = []
    cur: Optional[str] = None
    buf: List[str] = []

    def flush():
        if cur is not None:
            clauses[cur] = "\n".join(buf).strip()

    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        key = _clause_key(text)
        if key:
            flush()
            cur = key
            if key not in order:
                order.append(key)
            buf = [text]
        elif cur is not None:
            buf.append(text)
    flush()
    return clauses, order


def compare_clauses(paths: List[str]) -> Dict:
    names: List[str] = []
    per: Dict[str, Dict[str, str]] = {}
    all_keys: List[str] = []
    seen = set()

    for path in paths:
        clauses, order = extract_clauses(path)
        name = os.path.basename(path)
        names.append(name)
        per[name] = clauses
        for k in order:
            if k not in seen:
                seen.add(k)
                all_keys.append(k)

    results: List[Dict] = []
    summary = {"same": 0, "differs": 0, "missing_in_some": 0}
    for k in all_keys:
        versions = {name: per[name].get(k) for name in names}
        present = [v for v in versions.values() if v is not None]
        if len(present) < len(names):
            status = "missing_in_some"
        elif len(set(present)) > 1:
            status = "differs"
        else:
            status = "same"
        summary[status] += 1
        results.append({"clause": k, "status": status, "versions": versions})

    has_diff = summary["differs"] + summary["missing_in_some"] > 0
    return {
        "documents": names,
        "has_diff": has_diff,
        "summary": summary,
        "clauses": results,
    }
