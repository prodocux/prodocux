from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMAS = Path(__file__).resolve().parents[1] / "prodocux_kernel" / "schemas"
NAMES = (
    "prodocux_document_structure_profile_v1.json",
    "prodocux_template_conformance_request_v1.json",
    "prodocux_template_conformance_result_v1.json",
)


def _load(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def _registry() -> Registry:
    registry = Registry()
    for name in NAMES:
        schema = _load(name)
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(name, resource)
        registry = registry.with_resource(schema["$id"], resource)
    return registry


def test_proposal_schemas_compile_and_request_is_bilateral() -> None:
    for name in NAMES:
        Draft202012Validator.check_schema(_load(name))
    profile = {
        "schema_version": "prodocux_document_structure_profile_v1",
        "source_sha256": "a" * 64,
        "document_kind": "docx",
        "tables": [{
            "table_id": "table:001", "ordinal": 0, "row_count": 2,
            "column_count": 2, "header_rows": [0], "merge_ranges": [],
            "columns": [{"ordinal": 0, "header": "Shot"}, {"ordinal": 1, "header": "Duration"}],
            "style": {"style_name": "Table Grid"},
        }],
        "interpretation": "none",
    }
    request = {
        "schema_version": "prodocux_template_conformance_request_v1",
        "request_id": "request:001", "reference": profile,
        "candidate": {**profile, "source_sha256": "b" * 64},
        "policy": {"table_matching": "table_id", "protected": ["topology", "headers"], "allowed": ["body_text"]},
    }
    Draft202012Validator(_load(NAMES[1]), registry=_registry()).validate(request)


def test_result_conditions_and_closed_error_codes() -> None:
    validator = Draft202012Validator(_load(NAMES[2]))
    base = {
        "schema_version": "prodocux_template_conformance_result_v1",
        "request_id": "request:001", "reference_sha256": "a" * 64,
        "candidate_sha256": "b" * 64, "policy_digest": "c" * 64,
        "interpretation": "none",
    }
    assert not list(validator.iter_errors({**base, "conforms": True, "issues": []}))
    assert list(validator.iter_errors({**base, "conforms": True, "issues": [{"code": "HEADER_CHANGED", "location": "table:001/header:0", "message": "changed"}]}))
    assert list(validator.iter_errors({**base, "conforms": False, "issues": []}))
    assert list(validator.iter_errors({**base, "conforms": False, "issues": [{"code": "MADE_UP", "location": "x", "message": "x"}]}))


def test_proposal_manifest_locks_schema_bytes_without_authorizing_runtime() -> None:
    manifest_path = SCHEMAS.parents[1] / "docs" / "template-conformance" / "proposal-manifest.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "frozen_bilateral_contract"
    assert manifest["implementation_authorized"] is False
    assert manifest["schemas"] == {
        name: hashlib.sha256((SCHEMAS / name).read_bytes()).hexdigest()
        for name in NAMES
    }
