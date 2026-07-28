"""docops/pagination: deterministic cleanup of page breaks and blank pages.

Handles redundant page breaks / blank pages; the strategy is parameterized by
the profile's template_rules.pagination and is not bound to fixed heading
text.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Set

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph


def clear_paragraph(paragraph: Paragraph) -> None:
    """Clear a paragraph's content but keep its pPr (paragraph properties, possibly including sectPr)."""
    for child in list(paragraph._p):
        if child.tag != qn("w:pPr"):
            paragraph._p.remove(child)


def _para_has_page_break(p_element) -> bool:
    return any(br.get(qn("w:type")) == "page" for br in p_element.findall(".//" + qn("w:br")))


def _next_nonempty_paragraph(body: List, start_idx: int, doc: Document):
    for child in body[start_idx:]:
        if child.tag != qn("w:p"):
            continue
        paragraph = Paragraph(child, doc)
        if paragraph.text.strip():
            return paragraph
    return None


def remove_blank_page_breaks_before_headings(doc: Document, heading_styles: Iterable[str]) -> int:
    """Remove redundant page breaks: a blank paragraph containing a page break whose next non-empty paragraph is a heading.

    Returns the number of paragraphs removed. This kind of leftover page
    break is the most common source of blank pages after deleting images or
    content.
    """
    styles: Set[str] = set(heading_styles)
    body = list(doc.element.body.iterchildren())
    removed = 0
    for idx, child in enumerate(body):
        if child.tag != qn("w:p"):
            continue
        paragraph = Paragraph(child, doc)
        if paragraph.text.strip():
            continue
        if not _para_has_page_break(child):
            continue
        nxt = _next_nonempty_paragraph(body, idx + 1, doc)
        if nxt is not None and nxt.style and nxt.style.name in styles:
            child.getparent().remove(child)
            removed += 1
    return removed


def _normalized_mapped_headings(mapped_headings: Iterable[str]) -> Set[str]:
    from .sections import normalize_heading

    return {normalize_heading(h) for h in mapped_headings if h}


def _should_apply_page_break(
    paragraph: Paragraph,
    *,
    mode: str,
    heading_styles: Set[str],
    mapped_norm: Set[str],
    break_styles: Set[str],
) -> bool:
    name = paragraph.style.name if paragraph.style else ""
    if name not in heading_styles or not paragraph.text.strip():
        return False
    from .sections import normalize_heading

    norm = normalize_heading(paragraph.text.strip())
    if mode == "mapped_sections_only":
        return norm in mapped_norm
    if mode == "break_before_styles":
        return name in break_styles
    if mode == "all_heading_styles":
        return True
    return False


def set_heading_page_breaks(
    doc: Document,
    heading_styles: Iterable[str],
    first_no_break: bool = True,
    *,
    mode: str = "mapped_sections_only",
    mapped_headings: Optional[Iterable[str]] = None,
    break_before_styles: Optional[Iterable[str]] = None,
) -> int:
    """Set page_break_before on heading paragraphs according to the policy.

    Default mode=mapped_sections_only: paginates only headings within
    mapping.sections; unmapped front-matter headings (e.g. template-built-in
    narrative/introduction) do not count toward first_no_break.

    When mode=none, no pagination is modified and 0 is returned.
    Returns the number of headings for which page_break_before=True was
    actually set.
    """
    if mode == "none":
        return 0

    styles: Set[str] = set(heading_styles)
    mapped_norm = _normalized_mapped_headings(mapped_headings or [])
    break_styles: Set[str] = set(break_before_styles or [])
    seen = False
    count = 0
    for paragraph in doc.paragraphs:
        if not _should_apply_page_break(
            paragraph,
            mode=mode,
            heading_styles=styles,
            mapped_norm=mapped_norm,
            break_styles=break_styles,
        ):
            continue
        if seen or not first_no_break:
            paragraph.paragraph_format.page_break_before = True
            count += 1
        seen = True
    return count


def count_page_breaks(doc: Document) -> int:
    return len(doc.element.xpath('.//w:br[@w:type="page"]'))


def apply_pagination_policy(
    doc: Document,
    heading_styles: Iterable[str],
    *,
    mode: str = "mapped_sections_only",
    first_no_break: bool = True,
    mapped_headings: Optional[Iterable[str]] = None,
    break_before_styles: Optional[Iterable[str]] = None,
    chapter_break_styles: Optional[Iterable[str]] = None,
) -> int:
    """Apply pagination according to the mapping policy; can layer a second pass of major-chapter-style (chapter_break_styles) rules."""
    total = 0
    if mode != "none":
        total += set_heading_page_breaks(
            doc,
            heading_styles,
            first_no_break=first_no_break,
            mode=mode,
            mapped_headings=mapped_headings,
            break_before_styles=break_before_styles,
        )
    if chapter_break_styles:
        total += set_heading_page_breaks(
            doc,
            chapter_break_styles,
            first_no_break=first_no_break,
            mode="break_before_styles",
            break_before_styles=chapter_break_styles,
        )
    return total


def expected_heading_page_breaks(
    doc: Document,
    heading_styles: Iterable[str],
    *,
    mode: str,
    first_no_break: bool,
    mapped_headings: Iterable[str],
    break_before_styles: Optional[Iterable[str]] = None,
    chapter_break_styles: Optional[Iterable[str]] = None,
) -> Dict[tuple[str, str], bool]:
    """Compute the expected page_break_before for each heading per policy (used by the L0 policy gate)."""
    from .sections import normalize_heading

    styles: Set[str] = set(heading_styles)
    mapped_norm = _normalized_mapped_headings(mapped_headings)
    break_styles: Set[str] = set(break_before_styles or [])
    chapter_styles: Set[str] = set(chapter_break_styles or [])

    expected: Dict[tuple[str, str], bool] = {}
    mapped_seen = False
    chapter_seen: Dict[str, bool] = {}

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text or not paragraph.style:
            continue
        name = paragraph.style.name
        if name not in styles and name not in chapter_styles:
            continue
        key = (name, normalize_heading(text))
        norm = key[1]
        want = False

        if mode != "none" and _should_apply_page_break(
            paragraph,
            mode=mode,
            heading_styles=styles,
            mapped_norm=mapped_norm,
            break_styles=break_styles,
        ):
            if mapped_seen or not first_no_break:
                want = True
            mapped_seen = True

        if name in chapter_styles:
            seen = chapter_seen.get(name, False)
            if seen or not first_no_break:
                want = want or True
            chapter_seen[name] = True

        if name in styles or name in chapter_styles:
            expected[key] = want

    return expected
