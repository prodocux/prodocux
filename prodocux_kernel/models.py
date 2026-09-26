"""Request/response models for the Kernel's external API (CONTRACT.md §4)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------- /v1/version ----------
class VersionResponse(BaseModel):
    kernel_version: str
    api_version: str
    frozen_model: str
    schemas: list[str] = Field(default_factory=list)


# ---------- /v1/validate-structure ----------
class ValidateStructureRequest(BaseModel):
    document_path: str
    reference_path: str | None = (
        None  # source/template needed for comparison-type invariants
    )


class InvariantResult(BaseModel):
    id: str
    passed: bool | None  # None means skipped
    status: Literal["checked", "skipped", "error"]
    code: str = ""  # language-neutral message code
    params: dict[str, Any] = Field(default_factory=dict)


class ValidateStructureResponse(BaseModel):
    kernel_version: str
    passed: bool  # overall: true if all checked invariants pass
    invariants: list[InvariantResult]


# ---------- /v1/intake/capabilities + /v1/intake/profile-table ----------
class IntakeFormatCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extensions: list[str] = Field(min_length=1)
    status: Literal["available", "planned", "external_pipeline_required"]
    operation: str = Field(min_length=1)
    max_bytes: int | None = Field(default=None, ge=1)
    max_pages: int | None = Field(default=None, ge=1)
    additional_operations: list[str] = Field(default_factory=list)


class IntakeCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["prodocux_intake_capabilities_v1"]
    kernel_version: str
    api_version: str
    formats: list[IntakeFormatCapability]


class ProjectionSourceAdmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_inline_bytes: int = Field(ge=1)
    inline_source: bool
    spooled_source: bool
    artifact_backed_source: bool
    oversized_source_disposition: Literal["SOURCE_TOO_LARGE"]


class ProjectionCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["docx", "pdf", "csv", "xlsx", "pptx", "image"]
    extensions: list[str] = Field(min_length=1)
    status: Literal["bounded_with_continuation", "bounded_without_continuation"]
    range_units: list[str]
    endpoint: str | None = None
    source_admission: ProjectionSourceAdmission
    limits: dict[str, int]
    known_uncontinuable_limits: list[str]


class ProjectionCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["prodocux_projection_capabilities_v1"]
    kernel_version: str
    api_version: str
    profiles: list[ProjectionCapability]


class TableProfileRequest(BaseModel):
    document_path: str | None = None
    document_b64: str | None = None
    document_filename: str = "table.csv"


class TableProfileResponse(BaseModel):
    kernel_version: str
    profile: dict[str, Any]


class WorkbookProfileRequest(BaseModel):
    document_path: str | None = None
    document_b64: str | None = None
    document_filename: str = "workbook.xlsx"


class WorkbookProfileResponse(BaseModel):
    kernel_version: str
    profile: dict[str, Any]


class DocumentProfileRequest(BaseModel):
    document_path: str | None = None
    document_b64: str | None = None
    document_filename: str = "document.docx"


class DocumentProfileResponse(BaseModel):
    kernel_version: str
    profile: dict[str, Any]


class PresentationProfileRequest(BaseModel):
    document_path: str | None = None
    document_b64: str | None = None
    document_filename: str = "presentation.pptx"


class PresentationProfileResponse(BaseModel):
    kernel_version: str
    profile: dict[str, Any]


class ImageProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_b64: str = Field(min_length=1, max_length=14_000_000)
    document_filename: str = Field(default="image.png", min_length=5, max_length=255)
    ocr_requested: bool = False


class ImageProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kernel_version: str
    profile: dict[str, Any]


class PdfExtractPagesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_filename: str = Field(min_length=3, max_length=255)
    document_b64: str = Field(min_length=1, max_length=14_000_000)
    max_pages: int = Field(default=50, ge=1, le=50)


class PdfExtractPage(BaseModel):
    page_number: int = Field(ge=1)
    text: str = Field(max_length=50_000)
    ocr_required: bool


class PdfTruncation(BaseModel):
    truncated: bool
    total_characters: int = Field(ge=0, le=500_000)


class PdfExtractPagesResponse(BaseModel):
    status: Literal["success", "ocr_required"]
    source_sha256: str
    page_count: int = Field(ge=0, le=50)
    pages: list[PdfExtractPage]
    truncation: PdfTruncation


class PdfContinuableProjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_filename: str = Field(min_length=3, max_length=255)
    document_b64: str = Field(min_length=1, max_length=14_000_000)
    cursor: dict[str, Any] | None = None
    max_pages: int = Field(default=50, ge=1, le=50)
    ocr_requested: bool = False


class CsvContinuableProjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_filename: str = Field(min_length=4, max_length=255)
    document_b64: str = Field(min_length=1, max_length=12_000_000)
    cursor: dict[str, Any] | None = None
    max_rows: int = Field(default=500, ge=1, le=500)


class XlsxContinuableProjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_filename: str = Field(min_length=5, max_length=255)
    document_b64: str = Field(min_length=1, max_length=23_000_000)
    cursor: dict[str, Any] | None = None
    max_rows: int = Field(default=500, ge=1, le=500)


class PptxContinuableProjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_filename: str = Field(min_length=5, max_length=255)
    document_b64: str = Field(min_length=1, max_length=45_000_000)
    cursor: dict[str, Any] | None = None
    max_slides: int = Field(default=50, ge=1, le=50)


class ImageTileProjectionRequest(ImageProfileRequest):
    cursor: dict[str, Any] | None = None
    max_tiles: int = Field(default=16, ge=1, le=16)
    tile_edge: int = Field(default=2048, ge=256, le=2048)


class ExtractBlocksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_filename: str = Field(min_length=3, max_length=255)
    document_b64: str | None = Field(
        default=None, min_length=1, max_length=45_000_000
    )
    document_artifact: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _exactly_one_document_source(self) -> ExtractBlocksRequest:
        has_b64 = self.document_b64 is not None
        has_artifact = self.document_artifact is not None
        if has_b64 == has_artifact:
            raise ValueError(
                "exactly one of document_b64 or document_artifact is required"
            )
        return self


class ContinuableProjectionRequest(ExtractBlocksRequest):
    """Bounded DOCX projection request; cursor is an opaque Kernel value."""

    cursor: dict[str, Any] | None = None
    max_blocks: int = Field(default=200, ge=1, le=200)


class IntakeMaterializeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_filename: str = Field(min_length=3, max_length=255)
    document_b64: str = Field(min_length=1, max_length=45_000_000)
    media_type: str = Field(min_length=1, max_length=128)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)


class DerivedArtifactStoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_name: str = Field(min_length=3, max_length=255)
    content_b64: str = Field(min_length=1, max_length=45_000_000)
    media_type: str = Field(min_length=1, max_length=128)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)


class OpaqueArtifactIdentityV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["prodocux_opaque_artifact_v1"]
    artifact_id: str = Field(min_length=1, max_length=128)
    uri: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0, le=104857600)
    media_type: str = Field(min_length=1, max_length=128)


class ArtifactRetrieveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["prodocux_artifact_retrieve_v1"]
    request_id: str = Field(min_length=1, max_length=128)
    artifact: OpaqueArtifactIdentityV1


# ---------- /v1/review ----------
class ReviewStartRequest(BaseModel):
    source_path: str
    template_path: str | None = None
    profile_id: str
    doc_id: str
    canonical_data: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    template_rendered: dict[str, Any] = Field(default_factory=dict)


class ReviewFieldRow(BaseModel):
    field: str
    source_snippet: str = ""
    extracted: Any = None
    template_rendered: Any = None
    confidence: float | None = None


class ReviewStartResponse(BaseModel):
    kernel_version: str
    doc_id: str
    fields: list[ReviewFieldRow]


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
    verdicts: list[ReviewVerdict]


class ReviewCommitResponse(BaseModel):
    kernel_version: str
    golden_path: str
    correction_count: int


# ---------- /v1/score ----------
class Prediction(BaseModel):
    canonical_data: dict[str, Any] = Field(default_factory=dict)
    output_path: str | None = None


class ScoreRequest(BaseModel):
    dataset: Literal["dev", "heldout"]
    doc_id: str
    profile_id: str | None = None
    prediction: Prediction


class ScoreResponse(BaseModel):
    kernel_version: str
    l0_gate: Literal["pass", "fail"]
    scores: dict[str, Any]
    acceptance: dict[str, Any]
    per_field: list[dict[str, Any]] | None = None  # None in heldout mode
