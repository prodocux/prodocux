from __future__ import annotations

import tomllib
from pathlib import Path


def test_default_distribution_does_not_force_pymupdf() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    required = [item.casefold() for item in project["dependencies"]]
    optional = [item.casefold() for item in project["optional-dependencies"]["pdf-mupdf"]]

    assert not any(item.startswith("pymupdf") for item in required)
    assert any(item.startswith("reportlab") for item in required)
    assert any(item.startswith("pymupdf") for item in optional)
