"""Working-tree floors for the Phase 5 dependency release blocker."""

from __future__ import annotations

from importlib.metadata import version


def _numeric_prefix(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for token in value.split("."):
        digits = ""
        for char in token:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def test_pypdf_meets_security_floor() -> None:
    assert _numeric_prefix(version("pypdf")) >= (6, 15, 0)


def test_starlette_meets_security_floor() -> None:
    assert _numeric_prefix(version("starlette")) >= (1, 6, 0)


def test_fastapi_is_compatible_set() -> None:
    assert _numeric_prefix(version("fastapi")) >= (0, 141, 1)
