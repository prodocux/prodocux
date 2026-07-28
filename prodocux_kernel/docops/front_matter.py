"""docops/front_matter: deterministic anchor-based replacement of cover-page and front-matter fields.

Writes values provided by drafts at the style/prefix anchors defined by the
mapping; contains no product-specific copy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from docx import Document
from docx.text.paragraph import Paragraph


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class FrontMatterAnchor:
    """A single cover-page/front-matter field anchor."""

    field: str
    style: Optional[str] = None
    occurrence: int = 1
    prefix: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> "FrontMatterAnchor":
        return cls(
            field=data["field"],
            style=data.get("style"),
            occurrence=int(data.get("occurrence", 1)),
            prefix=data.get("prefix"),
        )


def _style_name(paragraph: Paragraph) -> str:
    return paragraph.style.name if paragraph.style else ""


def _candidate_paragraphs(
    doc: Document,
    anchor: FrontMatterAnchor,
    *,
    stop_styles: Optional[Iterable[str]] = None,
) -> List[Paragraph]:
    """Collect candidate paragraphs matching the anchor criteria (only scans up to the first mapped heading)."""
    stop = set(stop_styles or [])
    candidates: List[Paragraph] = []
    for paragraph in doc.paragraphs:
        style = _style_name(paragraph)
        if style in stop and _collapse_ws(paragraph.text):
            break
        text = paragraph.text
        if anchor.style and style != anchor.style:
            continue
        if anchor.prefix:
            if not text.startswith(anchor.prefix):
                continue
        elif not _collapse_ws(text):
            continue
        candidates.append(paragraph)
    return candidates


def _set_paragraph_text(paragraph: Paragraph, text: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.text = text


def apply_front_matter(
    doc: Document,
    anchors: Sequence[FrontMatterAnchor],
    values: Dict[str, str],
    *,
    stop_styles: Optional[Iterable[str]] = None,
) -> int:
    """Replace cover-page/front-matter text at the anchors. Returns the number of fields written."""
    written = 0
    for anchor in anchors:
        value = values.get(anchor.field)
        if value is None or str(value).strip() == "":
            continue
        candidates = _candidate_paragraphs(doc, anchor, stop_styles=stop_styles)
        idx = anchor.occurrence - 1
        if idx < 0 or idx >= len(candidates):
            continue
        paragraph = candidates[idx]
        new_text = f"{anchor.prefix}{value}" if anchor.prefix else str(value)
        _set_paragraph_text(paragraph, new_text)
        written += 1
    return written
