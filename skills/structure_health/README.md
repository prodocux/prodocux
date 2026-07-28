# Word document structure health check

> Skill #6 — first-party deterministic structure audit

## One-liner

Catch Word structure defects (blank pages, TOC/page-number issues, broken
cross-refs) before delivery — locally, without uploading files.

## What it does

- Local-only execution (no upload)
- Deterministic rules (not an LLM guess)
- CI-friendly (`--fail-on high`)
- Includes remediation hints

## Audience

Anyone shipping formal Word deliverables (proposals, legal/regulatory packs).

## CLI

See `SKILL.md` and `health_check.py --help`.
