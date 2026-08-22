"""Strict models for bounded normalized structured diff."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from prodocux_kernel.verification.evidence_models import SourceReferenceV1


class StrictDiffModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NormalizedProfileV1(StrictDiffModel):
    document_id: str = Field(min_length=1, max_length=128)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    values: dict[str, Any]
    locators: dict[str, SourceReferenceV1] = Field(default_factory=dict, max_length=2000)

    @field_validator("locators")
    @classmethod
    def validate_locator_paths(
        cls, locators: dict[str, SourceReferenceV1]
    ) -> dict[str, SourceReferenceV1]:
        for path in locators:
            if len(path) > 512 or (path and not path.startswith("/")):
                raise ValueError("locator keys must be root or JSON Pointer paths")
        return locators


class NormalizedDiffRequestV1(StrictDiffModel):
    schema_version: Literal["prodocux_normalized_diff_request_v1"]
    before: NormalizedProfileV1
    after: NormalizedProfileV1
    string_normalization: Literal[
        "exact", "trim", "collapse_whitespace", "casefold"
    ] = "exact"
    max_changes: int = Field(default=1000, ge=1, le=2000)
    array_key_fields: dict[str, str] = Field(default_factory=dict, max_length=100)

    @field_validator("array_key_fields")
    @classmethod
    def validate_array_key_fields(cls, fields: dict[str, str]) -> dict[str, str]:
        for path, field in fields.items():
            if not path.startswith("/") or len(path) > 512:
                raise ValueError("array key paths must be bounded JSON Pointer paths")
            if not field or len(field) > 128:
                raise ValueError("array key field names must be bounded text")
        return fields


class NormalizedDiffChangeV1(StrictDiffModel):
    path: str = Field(max_length=512)
    kind: Literal["added", "removed", "changed", "type_changed"]
    reason_code: Literal[
        "VALUE_ADDED", "VALUE_REMOVED", "VALUE_CHANGED", "VALUE_TYPE_CHANGED"
    ]
    before_value: Any = None
    after_value: Any = None
    before_locator: SourceReferenceV1 | None = None
    after_locator: SourceReferenceV1 | None = None


class NormalizedDiffResultV1(StrictDiffModel):
    schema_version: Literal["prodocux_normalized_diff_result_v1"]
    verifier_id: Literal["prodocux.normalized_diff"]
    verifier_version: Literal["1"]
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["identical", "changed"]
    before_document_id: str = Field(min_length=1, max_length=128)
    after_document_id: str = Field(min_length=1, max_length=128)
    before_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    after_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    string_normalization: Literal[
        "exact", "trim", "collapse_whitespace", "casefold"
    ]
    changes: list[NormalizedDiffChangeV1] = Field(max_length=2000)
    total_changes: int = Field(ge=0, le=5000)
    truncated: bool
