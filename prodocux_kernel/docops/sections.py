"""docops/sections: heading-anchored section location and content replacement.

This is the core write model of flagship pipeline #4 — instead of
placeholders, it uses the template's existing heading structure as anchors
and replaces the paragraphs "between one heading and the next". Generalized
and parameterized into the kernel.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from .content import SectionContent


def normalize_heading(text: str) -> str:
    """Normalization for heading matching: strips non-alphanumerics (including underscore) and lowercases."""
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()


def insert_paragraph_after(paragraph: Paragraph, text: str, style: Optional[str] = None) -> Paragraph:
    """Insert a new paragraph after the given paragraph, optionally applying a style."""
    new_p = OxmlElement("w:p")
    run = OxmlElement("w:r")
    text_node = OxmlElement("w:t")
    text_node.set(qn("xml:space"), "preserve")
    text_node.text = text
    run.append(text_node)
    new_p.append(run)
    paragraph._p.addnext(new_p)
    inserted = Paragraph(new_p, paragraph._parent)
    if style:
        try:
            inserted.style = style
        except KeyError:
            pass
    return inserted


def find_section_ranges(
    doc: Document,
    headings: Dict[str, str],
    heading_styles: Iterable[str],
) -> List[Tuple[int, int, str]]:
    """Find the paragraph range [start, end) for each target heading (end is the next heading or end of document).

    headings: {normalized_heading -> section_id}. Returns
    (start_idx, end_idx, section_id). idx is the index into body children.
    """
    styles: Set[str] = set(heading_styles)
    children = list(doc.element.body.iterchildren())
    ranges: List[Tuple[int, int, str]] = []
    for idx, child in enumerate(children):
        if child.tag != qn("w:p"):
            continue
        paragraph = Paragraph(child, doc)
        section_id = headings.get(normalize_heading(paragraph.text.strip()))
        if not section_id:
            continue
        end = len(children)
        for probe in range(idx + 1, len(children)):
            if children[probe].tag != qn("w:p"):
                continue
            probe_p = Paragraph(children[probe], doc)
            style_name = probe_p.style.name if probe_p.style else ""
            if style_name in styles:
                end = probe
                break
        ranges.append((idx, end, section_id))
    return ranges


def _clear_range_children(
    children: List,
    start: int,
    end: int,
    doc: Document,
    *,
    keep_tbl=None,
    keep_tbls: Optional[Iterable] = None,
) -> None:
    from .pagination import clear_paragraph

    kept = set(keep_tbls or [])
    if keep_tbl is not None:
        kept.add(keep_tbl)
    for child in reversed(children[start + 1: end]):
        if child in kept:
            continue
        if child.tag == qn("w:p") and child.find(".//" + qn("w:sectPr")) is not None:
            clear_paragraph(Paragraph(child, doc))
        elif child.tag == qn("w:sectPr"):
            continue
        else:
            child.getparent().remove(child)


def replace_section_contents(
    doc: Document,
    contents: Dict[str, SectionContent],
    headings: Dict[str, str],
    heading_styles: Iterable[str],
    section_modes: Dict[str, str],
    body_style: Optional[str] = None,
    section_table_fills: Optional[Dict[str, str]] = None,
) -> tuple[int, int]:
    """Replace section content: supports both paragraphs and tables (e.g. ingredient tables).

    section_modes: {section_id -> "table"|"paragraphs"}, determines the table
    write strategy.
    section_table_fills: {section_id -> "full"|"preserve_row_labels"}.
    Returns (sections_written, tables_written).
    """
    from . import tables as tbl_ops

    table_fills = section_table_fills or {}
    children = list(doc.element.body.iterchildren())
    ranges = find_section_ranges(doc, headings, heading_styles)
    sections_written = 0
    tables_written = 0

    for start, end, section_id in reversed(ranges):
        content = contents.get(section_id)
        if content is None:
            continue
        heading = Paragraph(children[start], doc)
        mode = section_modes.get(section_id, "paragraphs")
        use_table = mode == "table" or content.has_table

        table_fill = table_fills.get(section_id, "full")
        use_label_fill = (
            table_fill == "preserve_row_labels"
            or content.table_fill_mode == "by_label"
        )

        section_tbl_els: List = []
        first_tbl_el = None
        if use_table:
            for child in children[start + 1: end]:
                if child.tag == qn("w:tbl"):
                    section_tbl_els.append(child)
                    if first_tbl_el is None:
                        first_tbl_el = child

        keep_tbls = section_tbl_els if use_label_fill and section_tbl_els else None
        _clear_range_children(
            children, start, end, doc,
            keep_tbl=first_tbl_el if not keep_tbls else None,
            keep_tbls=keep_tbls,
        )

        anchor = heading
        for line in content.paragraphs:
            anchor = insert_paragraph_after(anchor, line, body_style)

        if content.has_table:
            hdr = content.table_header_rows

            if use_label_fill and content.table_values:
                targets = [Table(el, doc) for el in section_tbl_els]
                if not targets:
                    table = tbl_ops.insert_table_after(anchor, rows=max(hdr + 1, 2), cols=2)
                    targets = [table]
                for table in targets:
                    tbl_ops.fill_table_by_row_labels(
                        table,
                        content.table_values,
                        start_row=0,
                    )
            else:
                if first_tbl_el is not None:
                    table = Table(first_tbl_el, doc)
                else:
                    cols = max((len(r) for r in content.table_rows), default=1)
                    total_rows = hdr + len(content.table_rows)
                    table = tbl_ops.insert_table_after(anchor, rows=total_rows, cols=cols)
                cols = max((len(r) for r in content.table_rows), default=1)
                total_rows = hdr + len(content.table_rows)
                if table.rows:
                    cols = max(cols, len(table.rows[0].cells))
                tbl_ops.ensure_table_rows(table, total_rows)
                tbl_ops.fill_table_data(table, content.table_rows, start_row=hdr)
            tables_written += 1

        sections_written += 1

    return sections_written, tables_written


def replace_sections(
    doc: Document,
    drafts: Dict[str, List[str]],
    headings: Dict[str, str],
    heading_styles: Iterable[str],
    body_style: Optional[str] = None,
) -> int:
    """Replace content under the corresponding heading using drafts ({section_id -> [paragraph text]}); paragraphs only, for backward compatibility."""
    contents = {sid: SectionContent(paragraphs=lines) for sid, lines in drafts.items()}
    modes = {sid: "paragraphs" for sid in drafts}
    written, _ = replace_section_contents(
        doc, contents, headings, heading_styles, modes, body_style=body_style
    )
    return written


def remove_images_in_section(
    doc: Document,
    heading_text: str,
    heading_styles: Iterable[str],
) -> int:
    """Remove all tables containing images within a heading's section (removes duplicate/leftover images). Returns the number of tables removed."""
    styles: Set[str] = set(heading_styles)
    body = list(doc.element.body.iterchildren())
    in_section = False
    removed = 0
    blip = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
    for child in body:
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, doc)
            text = paragraph.text.strip()
            style_name = paragraph.style.name if paragraph.style else ""
            if text == heading_text:
                in_section = True
                continue
            if in_section and style_name in styles and text and text != heading_text:
                in_section = False
        elif in_section and child.tag == qn("w:tbl"):
            if child.findall(".//" + blip):
                child.getparent().remove(child)
                removed += 1
    return removed
