# Number consistency audit

> Skill #7 — first-party deterministic numeric checks

## One-liner

Before you sign off on contracts, invoices, or budgets, catch amount mismatches
(e.g. numerals vs written amounts, totals vs line items) in seconds — locally.

## What it does

- Rule-based comparisons (no LLM)
- Local-only execution
- Focus on costly numeric inconsistencies
- CI-friendly (`--fail-on high`)

## Audience

Finance, accounting, legal, and ops teams reviewing numeric Word/Excel-derived
deliverables.

## CLI

See `SKILL.md` and `number_audit.py --help`.
