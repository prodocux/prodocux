"""Public wheel and source-boundary checks."""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wheel_includes_api_and_packaged_schemas() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    include = config["tool"]["setuptools"]["packages"]["find"]["include"]
    package_data = config["tool"]["setuptools"]["package-data"]
    assert "api*" in include
    assert "prodocux_kernel*" in include
    assert "schemas/*.json" in package_data["prodocux_kernel"]


def test_capabilities_schema_is_present_in_source_tree() -> None:
    schema = ROOT / "prodocux_kernel" / "schemas" / "prodocux_intake_capabilities_v1.json"
    assert schema.is_file()


def test_private_workspace_paths_are_not_part_of_release_sources() -> None:
    public_files = [ROOT / "README.md", ROOT / "CONTRACT.md", ROOT / "ARCHITECTURE.md"]
    forbidden = ("prodocux-labs", "incubator/", "incubator\\")
    for path in public_files:
        text = path.read_text(encoding="utf-8").casefold()
        assert not any(term in text for term in forbidden), path
