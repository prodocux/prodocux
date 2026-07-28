"""#2 Precise template format extraction: extracts the template's skeleton into a structured profile.

Outputs a language-neutral structure (headings, styles, writable ranges,
table shapes) for use by mapping and rendering. Fully deterministic, no LLM
calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Union

from docx import Document
from docx.document import Document as _DocxDocument
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from ..docops.sections import normalize_heading

PathOrDoc = Union[str, _DocxDocument]


@dataclass
class SectionSlot:
    """Description of one writable section in the template."""
    section_id: str
    heading: str
    found: bool
    heading_style: str = ""
    match: str = ""              # exact | contains | ""
    para_start: Optional[int] = None   # body child index (heading paragraph)
    para_end: Optional[int] = None     # body child index of the next heading (None = end of document)
    mode: str = ""              # table | paragraphs (passed in from config, optional)
    has_table: bool = False
    table_rows: Optional[int] = None
    table_cols: Optional[int] = None


@dataclass
class HeadingRecord:
    index: int                  # body child index
    style: str
    text: str


@dataclass
class TemplateProfile:
    heading_styles: List[str]
    body_style: str
    sections: List[SectionSlot]
    paragraph_count: int = 0
    table_count: int = 0
    discovered_headings: List[HeadingRecord] = field(default_factory=list)

    def section(self, section_id: str) -> Optional[SectionSlot]:
        return next((s for s in self.sections if s.section_id == section_id), None)

    @property
    def missing(self) -> List[str]:
        return [s.section_id for s in self.sections if not s.found]


def _as_doc(template: PathOrDoc) -> Document:
    return template if isinstance(template, _DocxDocument) else Document(str(template))


def discover_headings(doc: Document, heading_styles: Sequence[str]) -> List[HeadingRecord]:
    """List all heading paragraphs in the template that use one of heading_styles."""
    styles: Set[str] = set(heading_styles)
    records: List[HeadingRecord] = []
    for idx, child in enumerate(doc.element.body.iterchildren()):
        if child.tag != qn("w:p"):
            continue
        paragraph = Paragraph(child, doc)
        style = paragraph.style.name if paragraph.style else ""
        text = paragraph.text.strip()
        if style in styles and text:
            records.append(HeadingRecord(idx, style, text))
    return records


def _table_dims_in_range(children: List, start: int, end: int) -> Optional[tuple]:
    for child in children[start + 1:end]:
        if child.tag == qn("w:tbl"):
            rows = child.findall(qn("w:tr"))
            cols = 0
            if rows:
                cols = len(rows[0].findall(qn("w:tc")))
            return len(rows), cols
    return None


def extract_profile(
    template: PathOrDoc,
    sections: Sequence[Dict],
    heading_styles: Sequence[str],
    body_style: str = "",
) -> TemplateProfile:
    """Map the given section specs ({id, heading, mode?}) onto the template skeleton.

    Matching strategy: first try a normalized exact match, then fall back to
    a "contains" match. Returns whether each section exists, its paragraph
    range, and whether it contains a table.
    """
    doc = _as_doc(template)
    styles: Set[str] = set(heading_styles)
    children = list(doc.element.body.iterchildren())

    # Pre-build an index of all heading paragraphs (with their styles) for range computation
    para_records: List[HeadingRecord] = []
    for idx, child in enumerate(children):
        if child.tag != qn("w:p"):
            continue
        paragraph = Paragraph(child, doc)
        style = paragraph.style.name if paragraph.style else ""
        para_records.append(HeadingRecord(idx, style, paragraph.text.strip()))

    def find_heading(heading: str):
        norm = normalize_heading(heading)
        for rec in para_records:
            if normalize_heading(rec.text) == norm:
                return rec, "exact"
        for rec in para_records:
            if rec.text and norm and norm in normalize_heading(rec.text):
                return rec, "contains"
        return None, ""

    slots: List[SectionSlot] = []
    for spec in sections:
        section_id = spec["id"]
        heading = spec["heading"]
        mode = spec.get("mode", "")
        rec, match = find_heading(heading)
        if rec is None:
            slots.append(SectionSlot(section_id, heading, False, mode=mode))
            continue
        start = rec.index
        end = None
        for probe in para_records:
            if probe.index > start and probe.style in styles and probe.text:
                end = probe.index
                break
        dims = _table_dims_in_range(children, start, end if end is not None else len(children))
        slots.append(
            SectionSlot(
                section_id=section_id,
                heading=heading,
                found=True,
                heading_style=rec.style,
                match=match,
                para_start=start,
                para_end=end,
                mode=mode,
                has_table=dims is not None,
                table_rows=dims[0] if dims else None,
                table_cols=dims[1] if dims else None,
            )
        )

    return TemplateProfile(
        heading_styles=list(heading_styles),
        body_style=body_style,
        sections=slots,
        paragraph_count=len(doc.paragraphs),
        table_count=len(doc.tables),
        discovered_headings=discover_headings(doc, heading_styles),
    )
