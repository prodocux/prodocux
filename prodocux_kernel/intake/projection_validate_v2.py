"""Additive semantic validation for explicitly selected Office v2 projections."""
from copy import deepcopy

from .projection_validate import (
    ProjectionValidationError,
    validate_continuable_projection,
)


def validate_office_projection_v2(value):
    schema = value.get("schema_version")
    if schema not in {"prodocux_csv_continuable_projection_v2", "prodocux_xlsx_continuable_projection_v2"}:
        raise ProjectionValidationError("unsupported Office v2 projection schema")
    if schema == "prodocux_xlsx_continuable_projection_v2" and value.get("range", {}).get("sheet_visibility") not in {
        "visible", "hidden", "veryHidden"
    }:
        raise ProjectionValidationError("XLSX v2 sheet visibility is required")
    # Reuse the unchanged v1 cross-field rules on the shared envelope.
    shared = deepcopy(dict(value))
    shared["schema_version"] = schema[:-1] + "1"
    validate_continuable_projection(shared)
