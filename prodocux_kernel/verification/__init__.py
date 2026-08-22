"""Product-neutral deterministic verification primitives."""

from prodocux_kernel.verification.evidence import (
    EvidenceValidationError,
    verify_evidence_bundle,
)
from prodocux_kernel.verification.structured_diff import (
    NormalizedDiffError,
    compare_normalized_profiles,
)

__all__ = [
    "EvidenceValidationError",
    "NormalizedDiffError",
    "compare_normalized_profiles",
    "verify_evidence_bundle",
]
