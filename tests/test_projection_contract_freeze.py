from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "projection-continuation" / "contract-freeze.v1.json"
SCHEMAS = ROOT / "prodocux_kernel" / "schemas"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_projection_contract_freeze_matches_reviewed_bytes() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "frozen"
    assert manifest["scope"]["large_pdf_continuation_included"] is False
    assert manifest["contracts"] == {
        name: _sha256(SCHEMAS / name) for name in manifest["contracts"]
    }
    assert set(manifest) == {
        "schema_version",
        "status",
        "frozen_at",
        "scope",
        "contracts",
    }
