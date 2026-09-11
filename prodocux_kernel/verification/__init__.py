"""Product-neutral deterministic verification primitives."""

from prodocux_kernel.verification.evidence import (
    EvidenceValidationError,
    verify_evidence_bundle,
)
from prodocux_kernel.verification.structured_diff import (
    NormalizedDiffError,
    compare_normalized_profiles,
)
from prodocux_kernel.verification.template_conformance import (
    compare_template_conformance,
    profile_docx_table_structure,
    profile_docx_table_structure_bytes,
    profile_pptx_table_structure,
    profile_pptx_table_structure_bytes,
    profile_xlsx_table_structure,
    profile_xlsx_table_structure_bytes,
)

__all__ = [
    "EvidenceValidationError",
    "NormalizedDiffError",
    "compare_normalized_profiles",
    "compare_template_conformance",
    "profile_docx_table_structure",
    "profile_docx_table_structure_bytes",
    "profile_pptx_table_structure",
    "profile_pptx_table_structure_bytes",
    "profile_xlsx_table_structure",
    "profile_xlsx_table_structure_bytes",
    "verify_evidence_bundle",
]
