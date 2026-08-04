"""Request/response models for the Kernel's external API (CONTRACT.md §4)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field


# ---------- /v1/version ----------
class VersionResponse(BaseModel):
    kernel_version: str
    api_version: str
    frozen_model: str
    schemas: List[str] = Field(default_factory=list)


# ---------- /v1/validate-structure ----------
class ValidateStructureRequest(BaseModel):
    document_path: str
    reference_path: Optional[str] = None  # source/template needed for comparison-type invariants


class InvariantResult(BaseModel):
    id: str
    passed: Optional[bool]  # None means skipped
    status: Literal["checked", "skipped", "error"]
    code: str = ""                                  # language-neutral message code
    params: Dict[str, Any] = Field(default_factory=dict)


class ValidateStructureResponse(BaseModel):
    kernel_version: str
    passed: bool  # overall: true if all checked invariants pass
    invariants: List[InvariantResult]


# ---------- /v1/intake/capabilities + /v1/intake/profile-table ----------
class TableProfileRequest(BaseModel):
    document_path: Optional[str] = None
    document_b64: Optional[str] = None
    document_filename: str = "table.csv"


class TableProfileResponse(BaseModel):
    kernel_version: str
    profile: Dict[str, Any]


class WorkbookProfileRequest(BaseModel):
    document_path: Optional[str] = None
    document_b64: Optional[str] = None
    document_filename: str = "workbook.xlsx"


class WorkbookProfileResponse(BaseModel):
    kernel_version: str
    profile: Dict[str, Any]


class DocumentProfileRequest(BaseModel):
    document_path: Optional[str] = None
    document_b64: Optional[str] = None
    document_filename: str = "document.docx"


class DocumentProfileResponse(BaseModel):
    kernel_version: str
    profile: Dict[str, Any]


class PresentationProfileRequest(BaseModel):
    document_path: Optional[str] = None
    document_b64: Optional[str] = None
    document_filename: str = "presentation.pptx"


class PresentationProfileResponse(BaseModel):
    kernel_version: str
    profile: Dict[str, Any]


# ---------- /v1/review ----------
class ReviewStartRequest(BaseModel):
    source_path: str
    template_path: Optional[str] = None
    profile_id: str
    doc_id: str
    canonical_data: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    confidence: Dict[str, float] = Field(default_factory=dict)
    template_rendered: Dict[str, Any] = Field(default_factory=dict)


class ReviewFieldRow(BaseModel):
    field: str
    source_snippet: str = ""
    extracted: Any = None
    template_rendered: Any = None
    confidence: Optional[float] = None


class ReviewStartResponse(BaseModel):
    kernel_version: str
    doc_id: str
    fields: List[ReviewFieldRow]


class ReviewVerdict(BaseModel):
    field: str
    extraction_verdict: Literal["correct", "wrong", "partial"]
    template_verdict: Literal["correct", "wrong"]
    gold_value: Any = None
    source_snippet: str = ""
    extracted: Any = None
    template_rendered: Any = None
    note: str = ""


class ReviewCommitRequest(BaseModel):
    doc_id: str
    schema_ref: str
    split: Literal["dev", "heldout"] = "dev"
    reviewed_by: str = "human"
    verdicts: List[ReviewVerdict]


class ReviewCommitResponse(BaseModel):
    kernel_version: str
    golden_path: str
    correction_count: int


# ---------- /v1/score ----------
class Prediction(BaseModel):
    canonical_data: Dict[str, Any] = Field(default_factory=dict)
    output_path: Optional[str] = None


class ScoreRequest(BaseModel):
    dataset: Literal["dev", "heldout"]
    doc_id: str
    profile_id: Optional[str] = None
    prediction: Prediction


class ScoreResponse(BaseModel):
    kernel_version: str
    l0_gate: Literal["pass", "fail"]
    scores: Dict[str, Any]
    acceptance: Dict[str, Any]
    per_field: Optional[List[Dict[str, Any]]] = None  # None in heldout mode
