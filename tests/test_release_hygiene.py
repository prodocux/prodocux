"""Public wheel and source-boundary checks."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_RECORD_TREES = [ROOT / "docs", ROOT / "compatibility"]
PUBLIC_TEXT_SUFFIXES = {
    ".md", ".py", ".toml", ".json", ".yml", ".yaml", ".mjs",
    ".ipynb", ".ps1",
}
PUBLIC_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".tmp",
    "build",
    "dist",
    "pifgen_inputs_test",
    "tests",
}
HISTORICAL_PRODUCT_PATTERN = (
    r"case[-_ ]?memory|cinema|fortified[-_ ]?enterprise[-_ ]?fleet|"
    r"\bfleet\b|handcheck|crdb[-_ ]?agent[-_ ]?memory|datahub[-_ ]?gate|"
    r"evidence[-_ ]?gate|local[-_ ]?ai|reviewdesk|roadstar|shelfready|"
    r"studio.?tower|\bfarpals\b|free[-_ ]?studio[-_ ]?flow|\bfsf\b|"
    r"b-?roll|wordpress|woocommerce|kaggle|devpost|opencv|connectome|tlorder"
)


def _public_text_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix.casefold() in PUBLIC_TEXT_SUFFIXES
        and not (set(path.relative_to(ROOT).parts) & PUBLIC_EXCLUDED_PARTS)
    ]


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
    forbidden = ("prodocux-labs", "incubator/", "incubator\\")
    for path in _public_text_files():
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


GENERIC_WINDOWS_INSTALL_PROBES = re.compile(
    r"(?i)C:\\Python31[123]\\python\.exe|C:\\path\\to\\python\.exe"
)


def _strip_allowed_windows_install_probes(relative: str, text: str) -> str:
    if relative == "runtime/install.ps1":
        return GENERIC_WINDOWS_INSTALL_PROBES.sub("", text)
    return text


def test_public_documents_have_no_windows_checkout_paths() -> None:
    windows_path = re.compile(r"(?i)\b[A-Z]:\\")
    found = []
    for path in _public_text_files():
        relative = path.relative_to(ROOT).as_posix()
        text = _strip_allowed_windows_install_probes(
            relative, path.read_text(encoding="utf-8")
        )
        if windows_path.search(text):
            found.append(relative)
    assert found == []


def test_install_probe_allowlist_does_not_hide_other_windows_paths() -> None:
    text = "C:\\Python311\\python.exe C:\\Users\\private\\python.exe"
    sanitized = _strip_allowed_windows_install_probes("runtime/install.ps1", text)
    assert "C:\\Python311\\python.exe" not in sanitized
    assert "C:\\Users\\private\\python.exe" in sanitized
    assert re.search(r"(?i)\b[A-Z]:\\", sanitized)


def test_consumer_provenance_is_not_stored_in_public_docs() -> None:
    found = sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
        and "consumer-provenance" in path.name.casefold()
        and not (set(path.relative_to(ROOT).parts) & PUBLIC_EXCLUDED_PARTS)
    )
    assert found == []


def test_public_release_records_are_product_neutral() -> None:
    consumer_attribution = re.compile(HISTORICAL_PRODUCT_PATTERN, re.IGNORECASE)
    found = []
    for tree in PUBLIC_RECORD_TREES:
        for path in tree.rglob("*"):
            if (
                path.is_file()
                and path.suffix.casefold() in {".md", ".json"}
                and (
                    consumer_attribution.search(path.name)
                    or consumer_attribution.search(path.read_text(encoding="utf-8"))
                )
            ):
                found.append(path.relative_to(ROOT).as_posix())
    assert found == []


def test_complete_public_text_surface_has_no_historical_product_names() -> None:
    historical_names = re.compile(HISTORICAL_PRODUCT_PATTERN, re.IGNORECASE)
    found = [
        path.relative_to(ROOT).as_posix()
        for path in _public_text_files()
        if historical_names.search(path.name)
        or historical_names.search(path.read_text(encoding="utf-8"))
    ]
    assert found == []
