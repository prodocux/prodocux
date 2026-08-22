from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "prodocux_kernel" / "schemas"
EXAMPLES = ROOT / "examples" / "contracts"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry() -> Registry:
    source = _load(SCHEMAS / "prodocux_source_reference_v1.json")
    return Registry().with_resource(source["$id"], Resource.from_contents(source))


def test_new_evidence_schemas_are_valid_draft_2020_12() -> None:
    for name in (
        "prodocux_source_reference_v1.json",
        "prodocux_evidence_bundle_request_v1.json",
        "prodocux_evidence_bundle_result_v1.json",
    ):
        Draft202012Validator.check_schema(_load(SCHEMAS / name))


def test_evidence_request_example_matches_contract() -> None:
    schema = _load(SCHEMAS / "prodocux_evidence_bundle_request_v1.json")
    Draft202012Validator(schema, registry=_registry()).validate(
        _load(EXAMPLES / "evidence_bundle_request_v1.json")
    )


def test_evidence_result_example_matches_contract() -> None:
    schema = _load(SCHEMAS / "prodocux_evidence_bundle_result_v1.json")
    Draft202012Validator(schema).validate(
        _load(EXAMPLES / "evidence_bundle_result_v1.json")
    )


def test_source_reference_rejects_unbounded_or_unknown_data() -> None:
    schema = _load(SCHEMAS / "prodocux_source_reference_v1.json")
    value = _load(EXAMPLES / "evidence_bundle_request_v1.json")["evidence"][0][
        "source_reference"
    ]
    value["snippet"] = "x" * 2049
    value["credential"] = "not-allowed"
    errors = list(Draft202012Validator(schema).iter_errors(value))
    assert errors


def test_evidence_contracts_contain_no_domain_or_host_ownership_fields() -> None:
    forbidden = (
        "commerce_listing",
        "provider_poll_interval",
        "regulatory_conclusion",
        "tenant_id",
    )
    for path in (*SCHEMAS.glob("*evidence*.json"), *SCHEMAS.glob("*source_reference*.json")):
        text = path.read_text(encoding="utf-8").casefold()
        assert not any(term in text for term in forbidden), path
