"""#15 Document version diff engine (deterministic, no LLM calls).

Extracts paragraph and table row text in document body order, performs a
sequence comparison, and outputs added / removed / replaced redline changes.
"""
from __future__ import annotations

import difflib
from typing import Dict, List

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


def _blocks(doc: Document) -> List[str]:
    """Flatten paragraphs and table rows into text lines in document body order."""
    out: List[str] = []
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            text = Paragraph(child, doc).text.strip()
            if text:
                out.append(text)
        elif child.tag == qn("w:tbl"):
            table = Table(child, doc)
            for row in table.rows:
                line = " | ".join(c.text.strip() for c in row.cells)
                if line.strip(" |"):
                    out.append(line)
    return out


def compare_docx(old_path: str, new_path: str) -> Dict:
    a = _blocks(Document(old_path))
    b = _blocks(Document(new_path))
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)

    changes: List[Dict] = []
    summary = {"added": 0, "removed": 0, "replaced": 0}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            changes.append({"type": "replaced", "old": a[i1:i2], "new": b[j1:j2]})
            summary["replaced"] += 1
        elif tag == "delete":
            changes.append({"type": "removed", "old": a[i1:i2], "new": []})
            summary["removed"] += 1
        elif tag == "insert":
            changes.append({"type": "added", "old": [], "new": b[j1:j2]})
            summary["added"] += 1

    return {
        "old": old_path,
        "new": new_path,
        "changed": bool(changes),
        "summary": summary,
        "changes": changes,
    }
