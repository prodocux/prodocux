---
name: document-structure-health-check
title: Document Structure Health Check
version: 0.1.0
author: ProDocuX
license: MIT
tags: [word, docx, audit, structure, toc, qa]
inputs: [.docx]
deterministic: true
llm_required: false
languages: [en, zh-TW]
---

# Document Structure Health Check

Catch common Word structural defects **before delivery**: hardcoded tables of
contents, blank pages, broken cross-references, deleted section breaks, and
image-removal residue. **Deterministic, runs locally, no upload, no AI.**
Output in English by default; pass `--lang zh-TW` for Traditional Chinese.

## Why

Structural defects survive proofreading and embarrass you after delivery: a TOC
that never updates, a stray blank page, a `Reference source not found` error.
Rules catch these reliably where a human eye (and an LLM) may not.

## Checks

| Check | Severity | Needs `--reference` |
|---|---|---|
| `valid_docx` | critical | no |
| `toc_is_field` (TOC is a field, not hardcoded) | high | no |
| `cross_references_valid` | high | no |
| `no_blank_pages` | medium | no |
| `no_orphan_section_break` | medium | yes |
| `image_removal_no_residue` | medium | yes |

## Usage

```bash
python -m skills.structure_health.health_check report.docx
python -m skills.structure_health.health_check *.docx --reference original.docx
python -m skills.structure_health.health_check a.docx --lang zh-TW
python -m skills.structure_health.health_check a.docx --fail-on high   # CI gate
```

## Example output

```
File: report.docx
Overall: FAIL ❌ (2 failed, max severity: high)
------------------------------------------------------------
[FAIL] toc_is_field  (high)
        Looks like a hardcoded TOC (heading + page-number lines but no TOC field)
        Fix: Use Word's automatic TOC (References → Table of Contents).
[FAIL] cross_references_valid  (high)
        Found broken-reference text: "Error! Reference source not found"
        Fix: In Word select all and press F9, or fix the target bookmark/heading.
```

## i18n

- Default output language: **English** (`en`).
- Override per run: `--lang zh-TW`, or set env `PRODOCUX_LANG`.
- The kernel returns language-neutral structured data; this skill localizes it.

## Limitations

- Blank-page and hardcoded-TOC detection are heuristic.
- Comparison checks (`no_orphan_section_break`, `image_removal_no_residue`)
  require `--reference`.
- .docx only.
