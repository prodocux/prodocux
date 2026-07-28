"""Section draft content model (paragraphs + table)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Union

DraftEntry = Union[List[str], Dict[str, Any], str]


@dataclass
class SectionContent:
    paragraphs: List[str] = field(default_factory=list)
    table_rows: List[List[str]] = field(default_factory=list)
    table_header_rows: int = 1
    table_values: Dict[str, str] = field(default_factory=dict)
    table_fill_mode: str = "full"  # full | by_label

    @property
    def has_table(self) -> bool:
        return bool(self.table_rows) or bool(self.table_values)

    @property
    def has_paragraphs(self) -> bool:
        return bool(self.paragraphs)


def parse_draft_entry(entry: DraftEntry) -> SectionContent:
    if isinstance(entry, list):
        return SectionContent(paragraphs=[str(x) for x in entry])
    if isinstance(entry, str):
        return SectionContent(paragraphs=[entry])
    if not isinstance(entry, dict):
        raise TypeError(f"unsupported draft entry type: {type(entry)}")

    paragraphs = [str(x) for x in entry.get("paragraphs", [])]
    table_rows: List[List[str]] = []
    table_values: Dict[str, str] = {}
    header_rows = 1
    fill_mode = "full"

    if "table" in entry and isinstance(entry["table"], dict):
        tbl = entry["table"]
        raw_rows = tbl.get("rows", [])
        table_rows = [[str(c) for c in row] for row in raw_rows]
        header_rows = int(tbl.get("header_rows", 1))
        fill_mode = str(tbl.get("fill_mode", "full"))
        raw_values = tbl.get("values")
        if isinstance(raw_values, dict):
            table_values = {str(k): str(v) for k, v in raw_values.items()}
    elif "rows" in entry:
        raw_rows = entry["rows"]
        table_rows = [[str(c) for c in row] for row in raw_rows]
        header_rows = int(entry.get("header_rows", 1))
        fill_mode = str(entry.get("fill_mode", "full"))
        raw_values = entry.get("values")
        if isinstance(raw_values, dict):
            table_values = {str(k): str(v) for k, v in raw_values.items()}

    if table_values and fill_mode == "full":
        fill_mode = "by_label"

    return SectionContent(
        paragraphs=paragraphs,
        table_rows=table_rows,
        table_header_rows=max(0, header_rows),
        table_values=table_values,
        table_fill_mode=fill_mode,
    )


def parse_drafts(raw: Dict[str, DraftEntry]) -> Dict[str, SectionContent]:
    return {sid: parse_draft_entry(entry) for sid, entry in raw.items()}
