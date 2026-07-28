"""Optional regression against local historical DOCX samples.

Set PRODOCUX_OLD_DOCX_DIR to a directory of *.docx fixtures (not shipped in this repo).
"""
import os
from pathlib import Path

import pytest

from prodocux_kernel.audit.pif_tw import audit_pif_tw, load_checklist
from prodocux_kernel.docops.invariants import overall_passed, validate_structure
from prodocux_kernel.templating.mapping import MappingConfig

_OLD = os.environ.get("PRODOCUX_OLD_DOCX_DIR", "").strip()
OLD_DOCX = Path(_OLD) if _OLD else Path("__unset_PRODOCUX_OLD_DOCX_DIR__")
EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "pif_tw"
pytestmark = pytest.mark.skipif(
    not OLD_DOCX.is_dir(),
    reason="Set PRODOCUX_OLD_DOCX_DIR to run optional historical DOCX regressions",
)


def _find(suffix: str) -> Path:
    matches = sorted(OLD_DOCX.glob(f"*{suffix}*.docx"))
    assert matches, f"no file matching *{suffix}* in {OLD_DOCX}"
    return matches[0]


@pytest.fixture(scope="module")
def mapping():
    return MappingConfig.from_json(EXAMPLES / "template_mapping.json")


@pytest.fixture(scope="module")
def checklist():
    return load_checklist(EXAMPLES / "tw_pif_checklist.json")


def test_all_milestones_have_16_sections(mapping, checklist):
    for key in ("compiled_v3", "v18_no_blank_breaks", "v20_word_toc_appendix_fix"):
        r = audit_pif_tw(_find(key), mapping, checklist)
        assert r["sections_found"] == 16


def test_v3_broken_cross_references():
    invs = {i.id: i.passed for i in validate_structure(str(_find("compiled_v3")))
            if i.status == "checked"}
    assert invs["cross_references_valid"] is False


def test_v10_hardcoded_toc():
    invs = {i.id: (i.passed, i.code) for i in validate_structure(str(_find("v10_tox_meta_fix")))
            if i.status == "checked"}
    assert invs["toc_is_field"] == (False, "toc_is_field.hardcoded")


def test_v17_still_has_blank_pages():
    invs = [i for i in validate_structure(str(_find("v17_no_blank_pages"))) if i.id == "no_blank_pages"]
    assert invs and invs[0].passed is False
    assert invs[0].params.get("n", 0) >= 1


def test_v18_structure_passes():
    assert overall_passed(validate_structure(str(_find("v18_no_blank_breaks"))))


def test_v20_structure_passes():
    assert overall_passed(validate_structure(str(_find("v20_word_toc_appendix_fix"))))


def test_v18_pif_finds_review_markers(mapping, checklist):
    """Intentionally marked review terms should be caught by pif_audit."""
    r = audit_pif_tw(_find("v18_no_blank_breaks"), mapping, checklist)
    checks = {f["check"] for f in r["findings"]}
    assert "review_marker_in_section" in checks
