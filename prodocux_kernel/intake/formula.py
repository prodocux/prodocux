"""Deterministic INCI / formula table extraction from PDF page text."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Union

PathLike = Union[str, Sequence[Dict[str, Any]]]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_INCI_START = re.compile(
    r"presentazione degli ingredienti|ingredienti?\s*\(%?\s*inci|成分.*inci",
    re.I,
)
_INCI_HEADER = re.compile(r"ingredienti\s+%\s+cas|ingredient\s+%\s+cas|成分\s*%.*cas", re.I)
_INCI_STOP = re.compile(
    r"^totale\b|^total\b|elenco ingredienti in etichetta|toxicological|毒理|densità\s",
    re.I,
)


def parse_formula_rows(text: str) -> List[Dict[str, str]]:
    """Parse INCI presentation rows from combined EU PIF page text."""
    rows: List[Dict[str, str]] = []
    in_formula = False
    for raw in text.splitlines():
        line = _clean(raw)
        if not line:
            continue
        lower = line.lower()
        if _INCI_START.search(line):
            in_formula = True
            rows = []
            continue
        if _INCI_HEADER.search(line):
            in_formula = True
            continue
        if not in_formula:
            continue
        if _INCI_STOP.search(line):
            break
        row = _parse_inci_line(line)
        if row:
            rows.append(row)
    return rows[:100]


def _parse_inci_line(line: str) -> Dict[str, str] | None:
    m = re.match(
        r"^(?:\d+\.\s*)?(.+?)\s+([0-9]+(?:[,.][0-9]+)?)\s+"
        r"([0-9]{2,7}-[0-9]{2}-[0-9]|-)\s*(.*)$",
        line,
    )
    if m:
        func = _clean(m.group(4).split("Annex")[0].split("  ")[0])
        return {
            "ingredient": m.group(1).strip(),
            "percent": m.group(2).replace(",", "."),
            "cas": m.group(3),
            "function": func,
            "raw": line,
        }
    m2 = re.match(
        r"^(?:\d+\.\s*)?(Parfum|Fragrance)\s+([0-9]+(?:[,.][0-9]+)?)(?:\s+|$)",
        line,
        re.I,
    )
    if m2:
        return {
            "ingredient": m2.group(1).strip(),
            "percent": m2.group(2).replace(",", "."),
            "cas": "-",
            "function": "Perfuming",
            "raw": line,
        }
    m3 = re.match(
        r"^(?:\d+\.\s*)?(.+?)\s+([0-9]+(?:[,.][0-9]+)?)\s+([0-9]{2,7}-[0-9]{2}-[0-9])",
        line,
    )
    if m3:
        return {
            "ingredient": m3.group(1).strip(),
            "percent": m3.group(2).replace(",", "."),
            "cas": m3.group(3),
            "function": "",
            "raw": line,
        }
    return None


def formula_rows_to_draft(
    rows: Sequence[Dict[str, str]],
    *,
    default_function: str = "",
) -> Dict[str, Any]:
    """Convert parsed rows to ProDocuX ``03_formula`` draft table."""
    table_rows: List[List[str]] = []
    for row in rows:
        ing = (row.get("ingredient") or "").strip()
        pct = (row.get("percent") or "").strip()
        if not ing or not pct:
            continue
        if ing.lower() in ("totale", "total"):
            continue
        cas = (row.get("cas") or "-").strip() or "-"
        func = (row.get("function") or default_function).strip()
        table_rows.append([ing, pct, cas, func])
    return {
        "03_formula": {
            "table": {
                "header_rows": 1,
                "rows": table_rows,
            }
        }
    }


def extract_formula_draft_from_pages(
    pages: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Extract ``03_formula`` draft from ``pages.json`` page records."""
    text = "\n".join(p.get("text") or "" for p in pages)
    rows = parse_formula_rows(text)
    draft = formula_rows_to_draft(rows)
    draft["_meta"] = {"formula_row_count": len(rows), "table_row_count": len(draft["03_formula"]["table"]["rows"])}
    return draft
