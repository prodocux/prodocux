"""#3 Rendering: writes language-neutral drafts into the template and uses #6 invariants as the release gate.

Key point (aligned with CONTRACT.md): **the runtime does not call an LLM**.
Content drafting (semantics/preferences turned into data) is produced by the
solver side and passed in via `drafts`; this module only does deterministic
writing: heading-anchored replacement → structural polish (pagination /
tables / page numbers / TOC / numbering) → update-fields-on-open → L0
invariant gate.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from docx import Document

from ..docops import fields, front_matter, pagination, parts, review_marks, sections, tables
from ..docops.invariants import Invariant, overall_passed, validate_structure
from .mapping import MappingConfig

PathLike = Union[str, Path]


@dataclass
class FooterSpec:
    prefix: str = "Page "
    middle: str = " of "
    suffix: str = ""
    include_total: bool = True
    alignment: int = 1


@dataclass
class TocSpec:
    after_heading: str
    until_heading: Optional[str] = None
    switches: str = 'TOC \\o "1-3" \\h \\z \\u'


@dataclass
class RenderResult:
    output_path: str
    sections_written: int
    tables_written: int = 0
    front_matter_written: int = 0
    blank_breaks_removed: int = 0
    headings_paged: int = 0
    tables_fitted: int = 0
    toc_inserted: bool = False
    review_marked: int = 0
    invariants: List[Invariant] = field(default_factory=list)
    passed: bool = True

    @property
    def invariant_summary(self) -> Dict[str, Optional[bool]]:
        return {i.id: i.passed for i in self.invariants}


def render_document(
    template_path: PathLike,
    output_path: PathLike,
    drafts: Dict[str, Any],
    config: MappingConfig,
    *,
    toc: Optional[TocSpec] = None,
    footer: Optional[FooterSpec] = None,
    review_terms: Optional[List[str]] = None,
    critical_terms: Optional[List[str]] = None,
    page_break_per_heading: bool = True,
    fit_tables: bool = True,
    validate: bool = True,
) -> RenderResult:
    """Render the template using drafts, returning a RenderResult with L0 gate results.

    Supported drafts formats:
    - Paragraph sections: {section_id: ["line1", ...]} or {"paragraphs": [...]}
    - Table sections: {section_id: {"table": {"header_rows": 1, "rows": [[...], ...]}}}
    - Row-anchored tables: {"table": {"fill_mode": "by_label", "values": {"Label": "Value"}}}
    - Front matter: {"front_matter": {"field": "value", ...}}
    """
    from .drafts import parse_drafts
    template_path = Path(template_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template_path, output_path)

    doc = Document(str(output_path))
    heading_styles = set(config.heading_styles)
    headings = config.headings_index()

    section_drafts = dict(drafts)
    front_values = section_drafts.pop("front_matter", None)
    if not isinstance(front_values, dict):
        front_values = {}

    front_written = 0
    if config.front_matter and front_values:
        front_written = front_matter.apply_front_matter(
            doc,
            config.front_matter,
            {str(k): str(v) for k, v in front_values.items()},
            stop_styles=config.heading_styles,
        )

    contents = parse_drafts(section_drafts)
    section_modes = {s.id: s.mode for s in config.sections}
    section_table_fills = {s.id: s.table_fill for s in config.sections}
    written, tables_written = sections.replace_section_contents(
        doc,
        contents,
        headings,
        heading_styles,
        section_modes,
        body_style=config.body_style or None,
        section_table_fills=section_table_fills,
    )

    blank_removed = pagination.remove_blank_page_breaks_before_headings(doc, heading_styles)
    headings_paged = 0
    if page_break_per_heading:
        mapped_headings = [s.heading for s in config.sections]
        headings_paged = pagination.apply_pagination_policy(
            doc,
            heading_styles,
            mode=config.pagination.mode,
            first_no_break=config.pagination.first_no_break,
            mapped_headings=mapped_headings,
            break_before_styles=config.pagination.break_before_styles,
            chapter_break_styles=config.pagination.chapter_break_styles,
        )
    tables_fitted = (
        tables.fit_tables_to_page(doc)
        if tables.should_fit_tables(config.table_policy, fit_tables=fit_tables)
        else 0
    )

    if footer is not None:
        fields.set_footer_page_numbers(
            doc,
            prefix=footer.prefix,
            middle=footer.middle,
            suffix=footer.suffix,
            include_total=footer.include_total,
            alignment=footer.alignment,
        )

    toc_inserted = False
    if toc is not None:
        toc_inserted = fields.insert_toc_field(
            doc, after_heading=toc.after_heading, until_heading=toc.until_heading,
            switches=toc.switches,
        )

    review_marked = 0
    if review_terms:
        review_marked = review_marks.highlight_review_terms(
            doc, review_terms=review_terms, critical_terms=critical_terms or []
        )

    doc.save(str(output_path))

    # Auto-update TOC/page-number fields on open (zip layer)
    parts.enable_update_fields_on_open(output_path)

    invariants: List[Invariant] = []
    passed = True
    if validate:
        invariants = validate_structure(
            str(output_path),
            reference_path=str(template_path),
            heading_styles=config.heading_styles,
            pagination_policy=config.pagination,
            mapped_headings=[s.heading for s in config.sections],
        )
        passed = overall_passed(invariants)

    return RenderResult(
        output_path=str(output_path),
        sections_written=written,
        tables_written=tables_written,
        front_matter_written=front_written,
        blank_breaks_removed=blank_removed,
        headings_paged=headings_paged,
        tables_fitted=tables_fitted,
        toc_inserted=toc_inserted,
        review_marked=review_marked,
        invariants=invariants,
        passed=passed,
    )
