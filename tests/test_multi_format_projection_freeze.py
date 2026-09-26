from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "docs/continuable-extraction/contract-freeze.v1.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_multi_format_projection_freeze_matches_public_bytes() -> None:
    manifest = json.loads(FREEZE.read_text(encoding="utf-8"))
    assert manifest["status"] == "frozen"
    assert manifest["candidate_version"] == "0.3.0rc10"
    assert manifest["publication_authorized"] is False
    for name, digest in manifest["schemas"].items():
        assert _sha(ROOT / "prodocux_kernel/schemas" / name) == digest
    validator = manifest["semantic_validator"]
    assert _sha(ROOT / validator["path"]) == validator["sha256"]
    for name, digest in manifest["evidence"].items():
        assert _sha(FREEZE.parent / name) == digest
    for name, digest in manifest["legacy_compatibility"].items():
        assert _sha(ROOT / "compatibility" / name) == digest


def test_frozen_evidence_declares_aggregation_and_terminal_semantics() -> None:
    evidence = json.loads(
        (FREEZE.parent / "evidence-v1.json").read_text(encoding="utf-8")
    )
    assert evidence["ocr_aggregation_priority"] == [
        "unavailable",
        "not_performed",
        "performed_partial",
        "performed_complete",
        "not_evaluated",
    ]
    assert evidence["vectors"]["pdf_55_pages_50_plus_5"]["expected_blocks"] == 55
    assert (
        evidence["vectors"]["pdf_scanned_page_in_first_range"]["expected_coverage"]
        == "partial_unknown"
    )
