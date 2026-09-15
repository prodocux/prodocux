"""Public wheel and source-boundary checks."""

from __future__ import annotations

import tomllib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_wheel_includes_api_and_packaged_schemas() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    include = config["tool"]["setuptools"]["packages"]["find"]["include"]
    package_data = config["tool"]["setuptools"]["package-data"]
    assert "api*" in include
    assert "prodocux_kernel*" in include
    assert "schemas/*.json" in package_data["prodocux_kernel"]


def test_public_package_metadata_is_complete() -> None:
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE"]
    assert project["authors"]
    assert project["urls"]["Repository"] == "https://github.com/prodocux/prodocux"


def test_capabilities_schema_is_present_in_source_tree() -> None:
    schema = ROOT / "prodocux_kernel" / "schemas" / "prodocux_intake_capabilities_v1.json"
    assert schema.is_file()


def test_private_workspace_paths_are_not_part_of_release_sources() -> None:
    public_files = [ROOT / "README.md", ROOT / "CONTRACT.md", ROOT / "ARCHITECTURE.md"]
    forbidden = ("prodocux-labs", "incubator/", "incubator\\")
    for path in public_files:
        text = path.read_text(encoding="utf-8").casefold()
        assert not any(term in text for term in forbidden), path


def test_internal_document_classes_are_absent_from_public_tree() -> None:
    denied_names = {
        "PHASE0_DECISIONS.md",
        "PHASE1_STATUS.md",
        "PHASE3_STATUS.md",
        "SECURITY_CANDIDATE_EVIDENCE.md",
        "SECURITY_OS_ACCEPTANCE.md",
        "SECURITY_RUNTIME.md",
    }
    found = sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*.md")
        if path.name in denied_names
        and not any(part.startswith(".") for part in path.relative_to(ROOT).parts)
        and path.relative_to(ROOT).parts[0] not in {"build", "dist"}
    )
    assert found == []


def test_public_markdown_has_no_windows_checkout_paths() -> None:
    windows_path = re.compile(r"(?i)\b[A-Z]:\\")
    found = []
    for path in ROOT.rglob("*.md"):
        relative = path.relative_to(ROOT)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if relative.parts[0] in {"build", "dist"}:
            continue
        if windows_path.search(path.read_text(encoding="utf-8")):
            found.append(relative.as_posix())
    assert found == []
