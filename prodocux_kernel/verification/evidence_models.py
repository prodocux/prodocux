"""Strict API models for deterministic evidence-bundle verification."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ScalarValue = str | int | float | bool | None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PdfPageLocator(StrictModel):
    kind: Literal["pdf_page"]
    page: int = Field(ge=1, le=10_000)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)


class WorksheetLocator(StrictModel):
    kind: Literal["worksheet"]
    sheet: str = Field(min_length=1, max_length=128)
    cell_range: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Z]{1,3}[1-9][0-9]*(?::[A-Z]{1,3}[1-9][0-9]*)?$",
    )


class DocxLocator(StrictModel):
    kind: Literal["docx"]
    paragraph_index: int | None = Field(default=None, ge=0, le=1_000_000)
    table_index: int | None = Field(default=None, ge=0, le=100_000)
    row_index: int | None = Field(default=None, ge=0, le=1_000_000)
    column_index: int | None = Field(default=None, ge=0, le=100_000)


class PresentationLocator(StrictModel):
    kind: Literal["presentation"]
    slide: int = Field(ge=1, le=100_000)
    shape_id: str | None = Field(default=None, min_length=1, max_length=128)


class ImageRegionLocator(StrictModel):
    kind: Literal["image_region"]
    bbox: list[float] = Field(min_length=4, max_length=4)


SourceLocator = Annotated[
    PdfPageLocator
    | WorksheetLocator
    | DocxLocator
    | PresentationLocator
    | ImageRegionLocator,
    Field(discriminator="kind"),
]


class ExtractionIdentity(StrictModel):
    method: Literal[
        "native_text", "table_parser", "ocr", "image_decode", "host_supplied"
    ]
    extractor_id: str = Field(min_length=1, max_length=128)
    extractor_version: str = Field(min_length=1, max_length=64)


class SourceReferenceV1(StrictModel):
    schema_version: Literal["prodocux_source_reference_v1"]
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: str = Field(min_length=1, max_length=128)
    locator: SourceLocator
    snippet: str = Field(default="", max_length=2048)
    extraction: ExtractionIdentity
    truncated: bool

    @field_validator("locator")
    @classmethod
    def validate_locator_semantics(cls, locator: SourceLocator) -> SourceLocator:
        if isinstance(locator, DocxLocator) and (
            locator.paragraph_index is None and locator.table_index is None
        ):
            raise ValueError("docx locator requires paragraph_index or table_index")
        bbox = getattr(locator, "bbox", None)
        if bbox is not None:
            if any(value < 0 or value > 1 for value in bbox):
                raise ValueError("bbox coordinates must be between 0 and 1")
            if bbox[0] > bbox[2] or bbox[1] > bbox[3]:
                raise ValueError("bbox must satisfy left <= right and top <= bottom")
        return locator


class EvidenceRuleSet(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class EvidenceDocument(StrictModel):
    document_id: str = Field(min_length=1, max_length=128)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: str = Field(min_length=1, max_length=128)


class EvidenceItem(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    field_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$",
    )
    value_type: Literal[
        "string", "number", "integer", "boolean", "date", "version", "null"
    ]
    value: ScalarValue
    confidence: float = Field(ge=0, le=1)
    source_reference: SourceReferenceV1

    @field_validator("value")
    @classmethod
    def bound_string_value(cls, value: ScalarValue) -> ScalarValue:
        if isinstance(value, str) and len(value) > 4096:
            raise ValueError("string evidence value exceeds 4096 characters")
        return value


class EvidenceCheck(StrictModel):
    check_id: str = Field(min_length=1, max_length=128)
    kind: Literal[
        "presence", "equality", "numeric_range", "date_order", "version_match"
    ]
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    expected: ScalarValue = None
    minimum: float | None = None
    maximum: float | None = None
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True
    minimum_confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_ids must be unique")
        if not all(item and len(item) <= 128 for item in value):
            raise ValueError("evidence_ids must be bounded non-empty strings")
        return value

    @field_validator("expected")
    @classmethod
    def bound_expected_value(cls, value: ScalarValue) -> ScalarValue:
        if isinstance(value, str) and len(value) > 4096:
            raise ValueError("expected string exceeds 4096 characters")
        return value


class EvidenceBundleRequestV1(StrictModel):
    schema_version: Literal["prodocux_evidence_bundle_request_v1"]
    request_id: str = Field(min_length=1, max_length=128)
    rule_set: EvidenceRuleSet
    documents: list[EvidenceDocument] = Field(min_length=1, max_length=20)
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=500)
    checks: list[EvidenceCheck] = Field(min_length=1, max_length=200)


class EvidenceVerifierIdentity(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)


class EvidenceCheckResult(StrictModel):
    check_id: str = Field(min_length=1, max_length=128)
    status: Literal["pass", "fail", "review"]
    reason_codes: list[str] = Field(max_length=20)
    evidence_ids: list[str] = Field(max_length=20)
    expected: ScalarValue = None
    actual: ScalarValue = None
    details: dict[str, ScalarValue] = Field(default_factory=dict)


class EvidenceBundleResultV1(StrictModel):
    schema_version: Literal["prodocux_evidence_bundle_result_v1"]
    request_id: str = Field(min_length=1, max_length=128)
    canonical_request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    verifier: EvidenceVerifierIdentity
    rule_set: EvidenceRuleSet
    status: Literal["pass", "fail", "review"]
    results: list[EvidenceCheckResult] = Field(min_length=1, max_length=200)
