"""Phase 0 Kernel contracts: additive paper freeze, frozen manifests untouched."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PHASE0 = ROOT / "docs" / "phase0"
FROZEN = {
    "pdx_prodocux_compatibility_v1.json": (
        "0b860fc0a5693a96083de1560ff030398e762c9f0c9dc4c0975eceb1d6ca1303"
    ),
    "pdx_prodocux_compatibility_v2.json": (
        "c301aba7442b150b8186ce3b7cd8da99e9470ad0592c13f7f2818d38fd5f378e"
    ),
    "pdx_prodocux_compatibility_v3.json": (
        "9591ab363472db78efb64265e3050fa4626be43783f848d0888e732898486d2b"
    ),
}
FORBIDDEN = ("wordpress", "woocommerce", "farpals", "oauth")

EXAMPLES = {
    "prodocux_safe_error_v1.json": "safe_error.ok.json",
    "prodocux_filesystem_sink_record_v1.json": "filesystem_sink_record.ok.json",
    "prodocux_sidecar_auth_profile_v1.json": "sidecar_auth.self_hosted.json",
}


def _schema(name: str) -> dict:
    return json.loads((PHASE0 / "schemas" / name).read_text(encoding="utf-8"))


def _validate(schema: dict, instance: dict) -> list[str]:
    validator = Draft202012Validator(schema)
    return [err.message for err in validator.iter_errors(instance)]


def test_frozen_compatibility_bytes_are_unchanged() -> None:
    for name, digest in FROZEN.items():
        path = ROOT / "compatibility" / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_phase0_examples_validate() -> None:
    mtls = json.loads(
        (PHASE0 / "examples" / "sidecar_auth.production_mtls.json").read_text(
            encoding="utf-8"
        )
    )
    pairs = dict(EXAMPLES)
    for schema_name, example_name in pairs.items():
        instance = json.loads(
            (PHASE0 / "examples" / example_name).read_text(encoding="utf-8")
        )
        assert _validate(_schema(schema_name), instance) == []
    assert _validate(_schema("prodocux_sidecar_auth_profile_v1.json"), mtls) == []


def test_phase0_negatives_fail() -> None:
    cases = [
        ("prodocux_safe_error_v1.json", "safe_error.extra_stack.json"),
        ("prodocux_filesystem_sink_record_v1.json", "filesystem_sink.gs_uri.json"),
        ("prodocux_filesystem_sink_record_v1.json", "filesystem_sink.local_path.json"),
        ("prodocux_sidecar_auth_profile_v1.json", "sidecar_auth.body_logging.json"),
    ]
    for schema_name, negative_name in cases:
        instance = json.loads(
            (PHASE0 / "negative" / negative_name).read_text(encoding="utf-8")
        )
        assert _validate(_schema(schema_name), instance)


def test_phase0_schemas_omit_application_host_types() -> None:
    for path in (PHASE0 / "schemas").glob("*.json"):
        text = path.read_text(encoding="utf-8").casefold()
        for token in FORBIDDEN:
            assert token not in text, f"{path.name} contains {token}"


def test_filesystem_sink_uri_is_artifact_only() -> None:
    record = json.loads(
        (PHASE0 / "examples" / "filesystem_sink_record.ok.json").read_text(
            encoding="utf-8"
        )
    )
    assert record["uri"].startswith("artifact://")
    assert "gs://" not in record["uri"]
    assert not record["uri"].startswith("file:")


def test_safe_error_example_has_no_path_or_traceback() -> None:
    error = json.loads(
        (PHASE0 / "examples" / "safe_error.ok.json").read_text(encoding="utf-8")
    )
    lowered = error["message"].casefold()
    assert "traceback" not in lowered
    assert "\\" not in error["message"]
    assert "/app/" not in lowered


def test_phase0_not_packaged_as_kernel_schema() -> None:
    packaged = ROOT / "prodocux_kernel" / "schemas"
    phase0_names = {path.name for path in (PHASE0 / "schemas").glob("*.json")}
    packaged_names = {path.name for path in packaged.glob("*.json")}
    assert phase0_names.isdisjoint(packaged_names)


def _digest_files() -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(PHASE0.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(PHASE0).as_posix()
        if rel in {"fixture-digest-manifest.json", "README.md"}:
            continue
        if path.suffix != ".json":
            continue
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def test_fixture_digest_manifest_matches_hashed_files() -> None:
    computed = _digest_files()
    manifest = json.loads(
        (PHASE0 / "fixture-digest-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == "prodocux_phase0_fixture_digest_manifest_v1"
    assert manifest["algorithm"] == "sha256"
    assert manifest["canonicalization"] == (
        "raw UTF-8 file bytes as stored; JSON uses LF; no JSON re-encoding"
    )
    assert manifest["root"] == "docs/phase0"
    assert "fixture-digest-manifest.json" not in manifest["files"]
    assert manifest["files"] == computed
