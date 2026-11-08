"""Kernel freeze is verifiable without optional backend source or tools."""
import hashlib
import json
from pathlib import Path

import rfc8785
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def test_kernel_contract_freeze_is_self_contained():
    frozen = json.loads((ROOT / "docs/document-intake/contract-freeze.v1.json").read_text())
    assert frozen["status"] == "frozen"
    assert len(frozen["schemas"]) == 6
    for record in frozen["schemas"]:
        path = (ROOT / record["path"]).resolve()
        assert path.is_relative_to(ROOT.resolve())
        raw = path.read_bytes()
        schema = json.loads(raw)
        Draft202012Validator.check_schema(schema)
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
        assert hashlib.sha256(rfc8785.dumps(schema)).hexdigest() == record["jcs_sha256"]
    semantics = frozen["semantics"]
    raw = (ROOT / semantics["path"]).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(raw).hexdigest() == semantics["sha256_lf"]


def test_kernel_release_does_not_require_optional_backend():
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    assert "Publish unchanged distributions to PyPI" in workflow
    assert "adapters/" not in workflow
    assert "pdx_document_backend" not in workflow
    assert "document-backend-release.yml" not in workflow
