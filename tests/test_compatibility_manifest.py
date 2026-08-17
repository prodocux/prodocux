from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prodocux_kernel import API_VERSION, __version__


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "compatibility" / "pdx_prodocux_compatibility_v1.json"
SCHEMAS = ROOT / "prodocux_kernel" / "schemas"


def test_compatibility_manifest_matches_prodocux_release_surface() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "pdx_prodocux_compatibility_v1"
    assert manifest["status"] == "release_candidate"

    surface = manifest["prodocux"]
    assert surface["distribution"] == "prodocux"
    assert surface["version"] == __version__
    assert surface["api_version"] == API_VERSION

    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in SCHEMAS.glob("*.json")
    }
    assert surface["schemas"] == actual
