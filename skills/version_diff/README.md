# Document version diff / red-line

> Skill #15 — first-party deterministic Word diff

## One-liner

Compare two Word files and list inserts, deletes, and changes — even when Track
Changes was never enabled.

## What it does

- Deterministic paragraph/table expansion
- Local-only execution
- Optional `--fail-on-change` gate

## Audience

Legal, procurement, editors, PMs, QA reviewing SOP revisions.

## CLI

See `SKILL.md` and `version_diff.py --help`.
