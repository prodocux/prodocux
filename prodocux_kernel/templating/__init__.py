"""Templating layer: flagship pipeline #2 template extraction / #1 field mapping / #3 rendering.

Design principles (aligned with CONTRACT.md):
- Fully deterministic; **the runtime does not call an LLM**. Content drafting
  (the semantic part of #3) is produced by the solver side; this module only
  "renders the language-neutral draft into the template" and uses #6
  invariants as the release gate.
- No placeholders; uses heading-anchored paragraph replacement (see
  docops.sections).
"""
from . import mapping, profile, render  # noqa: F401

__all__ = ["mapping", "profile", "render"]
