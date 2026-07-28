"""Document operations layer: deterministic docx structure checks and manipulation (including L0 invariants).

The flagship pipeline's doc-ops layer: structural fixes generalized and
parameterized, with regression tests locking down behavior. Fully
deterministic, no LLM calls.
"""
from . import fields, pagination, parts, review_marks, sections, tables  # noqa: F401

__all__ = ["fields", "pagination", "parts", "review_marks", "sections", "tables"]
