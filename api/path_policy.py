"""Local-path policy for colocated ProDocuX API deployments."""

from __future__ import annotations

import os
from pathlib import Path

_ROOTS_ENV = "PRODOCUX_ALLOWED_INPUT_ROOTS"


def resolve_allowed_input_path(value: str, *, suffix: str) -> Path:
    """Resolve an existing input file under an explicitly configured root."""
    configured = [item.strip() for item in os.environ.get(_ROOTS_ENV, "").split(os.pathsep)]
    roots = [Path(item).resolve() for item in configured if item]
    if not roots:
        raise ValueError(
            f"document_path is disabled; configure {_ROOTS_ENV} for colocated use"
        )

    candidate = Path(value)
    if candidate.suffix.casefold() != suffix.casefold():
        raise ValueError(f"document_path must end with {suffix}")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError("document_path must identify an existing file") from exc
    if not resolved.is_file():
        raise ValueError("document_path must identify an existing file")
    if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
        raise ValueError("document_path is outside configured input roots")
    return resolved
