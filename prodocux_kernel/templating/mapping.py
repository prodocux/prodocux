"""#1 Template field mapping: mapping-config schema + source_queries locator engine.

Given source-page text and a mapping config, deterministically matches each
section to its source pages. Fully deterministic, no LLM calls.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

from ..docops.front_matter import FrontMatterAnchor
from ..docops.tables import TABLE_POLICIES

PathLike = Union[str, Path]


PAGINATION_MODES = (
    "none",
    "mapped_sections_only",
    "all_heading_styles",
    "break_before_styles",
)


@dataclass
class PaginationPolicy:
    """Template pagination policy (provided by the profile's template_rules.pagination).

    - none: does not modify the template's existing pagination (cover page /
      front matter / sections stay as-is)
    - mapped_sections_only: paginates only headings in mapping.sections
      (unmapped front matter is not counted in the ordering)
    - all_heading_styles: paginates on all heading_styles headings (legacy
      behavior)
    - break_before_styles: paginates only on specified styles (e.g. major
      chapter heading style "PIF標題一")
    """

    mode: str = "mapped_sections_only"
    first_no_break: bool = True
    break_before_styles: List[str] = field(default_factory=list)
    chapter_break_styles: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "PaginationPolicy":
        if not data:
            return cls()
        mode = data.get("mode", "mapped_sections_only")
        return cls(
            mode=mode,
            first_no_break=bool(data.get("first_no_break", True)),
            break_before_styles=list(data.get("break_before_styles", [])),
            chapter_break_styles=list(data.get("chapter_break_styles", [])),
        )


TABLE_FILL_MODES = ("full", "preserve_row_labels")


@dataclass
class SectionSpec:
    id: str
    heading: str
    mode: str = "paragraphs"          # table | paragraphs
    detail: str = "standard"          # brief | standard | detailed
    source_queries: List[str] = field(default_factory=list)
    table_fill: str = "full"          # full | preserve_row_labels

    @classmethod
    def from_dict(cls, data: Dict) -> "SectionSpec":
        return cls(
            id=data["id"],
            heading=data["heading"],
            mode=data.get("mode", "paragraphs"),
            detail=data.get("detail", "standard"),
            source_queries=list(data.get("source_queries", [])),
            table_fill=data.get("table_fill", "full"),
        )


@dataclass
class MappingConfig:
    heading_styles: List[str]
    body_style: str
    sections: List[SectionSpec]
    remove_review_artifacts: List[str] = field(default_factory=list)
    pagination: PaginationPolicy = field(default_factory=PaginationPolicy)
    table_policy: str = "fit_to_page"
    front_matter: List[FrontMatterAnchor] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict) -> "MappingConfig":
        rules = data.get("template_rules", {})
        raw_front = data.get("front_matter", [])
        return cls(
            heading_styles=list(rules.get("heading_styles", [])),
            body_style=rules.get("body_style", ""),
            sections=[SectionSpec.from_dict(s) for s in data.get("sections", [])],
            remove_review_artifacts=list(rules.get("remove_review_artifacts", [])),
            pagination=PaginationPolicy.from_dict(rules.get("pagination")),
            table_policy=rules.get("table_policy", "fit_to_page"),
            front_matter=[FrontMatterAnchor.from_dict(a) for a in raw_front],
        )

    @classmethod
    def from_json(cls, path: PathLike) -> "MappingConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def headings_index(self) -> Dict[str, str]:
        """{normalized_heading -> section_id}, used by docops.sections replacement."""
        from ..docops.sections import normalize_heading
        return {normalize_heading(s.heading): s.id for s in self.sections}

    def section_specs(self) -> List[Dict]:
        """Convert to the {id, heading, mode} list accepted by profile.extract_profile."""
        return [{"id": s.id, "heading": s.heading, "mode": s.mode} for s in self.sections]


def validate_config(config: MappingConfig) -> List[str]:
    """Check config consistency; return a list of issues (empty = pass)."""
    issues: List[str] = []
    if not config.heading_styles:
        issues.append("template_rules.heading_styles 不可為空")
    seen = set()
    for spec in config.sections:
        if not spec.id:
            issues.append("有 section 缺少 id")
        elif spec.id in seen:
            issues.append(f"section id 重複：{spec.id}")
        seen.add(spec.id)
        if not spec.heading:
            issues.append(f"section {spec.id} 缺少 heading")
        if spec.mode not in ("table", "paragraphs"):
            issues.append(f"section {spec.id} 的 mode 非法：{spec.mode}")
        if spec.table_fill not in TABLE_FILL_MODES:
            issues.append(f"section {spec.id} 的 table_fill 非法：{spec.table_fill}")
    if config.table_policy not in TABLE_POLICIES:
        issues.append(
            f"template_rules.table_policy 非法：{config.table_policy} "
            f"（允許：{', '.join(TABLE_POLICIES)}）"
        )
    for anchor in config.front_matter:
        if not anchor.field:
            issues.append("front_matter 錨點缺少 field")
        elif not anchor.style and not anchor.prefix:
            issues.append(f"front_matter.{anchor.field} 需指定 style 或 prefix")
    if config.pagination.mode not in PAGINATION_MODES:
        issues.append(
            f"template_rules.pagination.mode 非法：{config.pagination.mode} "
            f"（允許：{', '.join(PAGINATION_MODES)}）"
        )
    if config.pagination.mode == "break_before_styles" and not config.pagination.break_before_styles:
        issues.append("pagination.mode=break_before_styles 時 break_before_styles 不可為空")
    return issues


@dataclass
class SourceHit:
    file: str
    page: int
    score: int
    snippet: str


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def best_page_snippet(text: str, queries: Sequence[str], limit: int = 1800) -> str:
    """Extract the snippet closest to where a query keyword was matched."""
    lower = text.lower()
    positions = [lower.find(q.lower()) for q in queries if lower.find(q.lower()) >= 0]
    if not positions:
        return _clean(text[:limit])
    start = max(0, min(positions) - 240)
    return _clean(text[start:start + limit])


def map_sources_to_sections(
    pages: Sequence[Dict],
    config: MappingConfig,
    limit: int = 5,
    snippet_limit: int = 1800,
) -> Dict[str, List[SourceHit]]:
    """For each section, rank the most relevant source pages by source_queries hit count.

    pages: [{"file": str, "page": int, "text": str}, ...]
    Returns {section_id: [SourceHit, ...]} (sorted by descending score, top `limit` entries).
    """
    result: Dict[str, List[SourceHit]] = {}
    for spec in config.sections:
        hits: List[SourceHit] = []
        for page in pages:
            lower = (page.get("text") or "").lower()
            score = sum(1 for q in spec.source_queries if q.lower() in lower)
            if score:
                hits.append(
                    SourceHit(
                        file=page.get("file", ""),
                        page=page.get("page", 0),
                        score=score,
                        snippet=best_page_snippet(page.get("text") or "", spec.source_queries, snippet_limit),
                    )
                )
        hits.sort(key=lambda h: (-h.score, h.file, h.page))
        result[spec.id] = hits[:limit]
    return result


def evidence_pages(hits: Dict[str, List[SourceHit]], section_id: str, limit: int = 5) -> Optional[str]:
    """Format a section's hit pages as a 'p.1, p.3' string; return None if there are no hits."""
    section_hits = hits.get(section_id, [])
    pages: List[int] = []
    for hit in section_hits:
        if hit.page not in pages:
            pages.append(hit.page)
    if not pages:
        return None
    return ", ".join(f"p.{p}" for p in pages[:limit])
