"""Flagship pipeline: PDF text extraction → source mapping → template rendering → evidence image injection → L0 gate.

Fully deterministic; the runtime does not call an LLM. Semantic drafts are
passed in by the solver side.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from ..intake import evidence as ev
from ..intake import pdf as intake
from ..intake.pdf_images import extract_evidence_bundle
from ..docops.invariants import validate_structure, overall_passed
from .mapping import MappingConfig, SourceHit, map_sources_to_sections
from .render import FooterSpec, RenderResult, TocSpec, render_document

PathLike = Union[str, Path]
SOURCE_MAP_SCHEMA = "prodocux_source_map_v1"


@dataclass
class PipelineResult:
    output_path: str
    render: RenderResult
    pages_path: Optional[str] = None
    source_map_path: Optional[str] = None
    evidence_index_path: Optional[str] = None
    pages_document: Optional[Dict[str, Any]] = None
    source_map: Optional[Dict[str, Any]] = None
    evidence_index: Optional[Dict[str, Any]] = None
    evidence_injection: Optional[Dict[str, Any]] = None
    passed: bool = True
    invariants: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output_path": self.output_path,
            "passed": self.passed,
            "pages_path": self.pages_path,
            "source_map_path": self.source_map_path,
            "evidence_index_path": self.evidence_index_path,
            "sections_written": self.render.sections_written,
            "tables_written": self.render.tables_written,
            "evidence_applied": (self.evidence_injection or {}).get("applied", 0),
            "invariants": self.render.invariant_summary,
        }


def _serialize_source_map(hits: Dict[str, List[SourceHit]]) -> Dict[str, Any]:
    sections: Dict[str, List[Dict[str, Any]]] = {}
    for section_id, section_hits in hits.items():
        sections[section_id] = [
            {
                "file": h.file,
                "page": h.page,
                "score": h.score,
                "snippet": h.snippet,
            }
            for h in section_hits
        ]
    return {"schema": SOURCE_MAP_SCHEMA, "sections": sections}


def _write_json(data: Dict[str, Any], path: PathLike) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out)


def run_flagship_pipeline(
    template_path: PathLike,
    output_path: PathLike,
    config: MappingConfig,
    drafts: Dict[str, Any],
    *,
    pdf_paths: Optional[Sequence[PathLike]] = None,
    pages_json: Optional[PathLike] = None,
    pages_out: Optional[PathLike] = None,
    source_map_out: Optional[PathLike] = None,
    evidence_spec: Optional[PathLike] = None,
    evidence_pdf: Optional[PathLike] = None,
    evidence_index_out: Optional[PathLike] = None,
    image_dir: Optional[PathLike] = None,
    ocr_fallback: bool = False,
    ocr_min_chars: int = 20,
    toc: Optional[TocSpec] = None,
    footer: Optional[FooterSpec] = None,
    review_terms: Optional[List[str]] = None,
    validate: bool = True,
) -> PipelineResult:
    """Execute intake → mapping → render → optional evidence → gate."""
    pages_doc: Optional[Dict[str, Any]] = None
    pages_path: Optional[str] = None

    if pages_json:
        pages_doc = intake.load_pages_json(pages_json)
    elif pdf_paths:
        pages_doc = intake.extract_pdfs(
            list(pdf_paths),
            ocr_fallback=ocr_fallback,
            ocr_min_chars=ocr_min_chars,
        )
        if pages_out:
            pages_path = intake.write_pages_json(pages_doc, pages_out)

    source_map_data: Optional[Dict[str, Any]] = None
    source_map_path: Optional[str] = None
    if pages_doc and pages_doc.get("pages"):
        hits = map_sources_to_sections(
            intake.pages_for_mapping(pages_doc["pages"]),
            config,
        )
        source_map_data = _serialize_source_map(hits)
        if source_map_out:
            source_map_path = _write_json(source_map_data, source_map_out)

    render_result = render_document(
        template_path,
        output_path,
        drafts,
        config,
        toc=toc,
        footer=footer,
        review_terms=review_terms,
        validate=validate,
    )

    evidence_index: Optional[Dict[str, Any]] = None
    evidence_index_path: Optional[str] = None
    injection_report: Optional[Dict[str, Any]] = None
    passed = render_result.passed

    if evidence_spec:
        spec = ev.load_evidence_spec(evidence_spec)
        pdf_for_evidence = evidence_pdf or (pdf_paths[0] if pdf_paths else None)
        if pdf_for_evidence:
            img_dir = Path(image_dir or Path(output_path).parent / "evidence_images")
            evidence_index = extract_evidence_bundle(pdf_for_evidence, spec, img_dir)
            injection_report = ev.apply_evidence_injections(
                render_result.output_path,
                spec,
                evidence_index.get("image_paths", {}),
                heading_styles=set(config.heading_styles),
            )
            evidence_index["injections_applied"] = injection_report["applied"]
            evidence_index["injections_skipped"] = injection_report["skipped"]
            evidence_index["injection_details"] = injection_report["details"]
            if evidence_index_out:
                evidence_index_path = _write_json(evidence_index, evidence_index_out)
            if validate:
                invariants = validate_structure(
                    render_result.output_path,
                    reference_path=str(template_path),
                    heading_styles=config.heading_styles,
                    pagination_policy=config.pagination,
                    mapped_headings=[s.heading for s in config.sections],
                    evidence_index=evidence_index if evidence_spec else None,
                    require_pymupdf=bool(evidence_spec),
                )
                render_result.invariants = invariants
                passed = overall_passed(invariants)
                render_result.passed = passed

    return PipelineResult(
        output_path=render_result.output_path,
        render=render_result,
        pages_path=pages_path,
        source_map_path=source_map_path,
        evidence_index_path=evidence_index_path,
        pages_document=pages_doc,
        source_map=source_map_data,
        evidence_index=evidence_index,
        evidence_injection=injection_report,
        passed=passed,
        invariants=render_result.invariants,
    )
