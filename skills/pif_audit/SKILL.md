---
name: taiwan-pif-compliance-audit
title: Taiwan PIF Compliance Audit
version: 0.1.0
author: ProDocuX
license: MIT
tags: [word, docx, audit, cosmetics, pif, taiwan, tfda, regulation]
inputs: [.docx]
deterministic: true
llm_required: false
languages: [en, zh-TW]
---

# Taiwan PIF Compliance Audit

Audit a Taiwan cosmetics **Product Information File (PIF)** against TFDA
**Article 3** (16 mandatory data items under the *化粧品產品資訊檔案管理辦法*)
plus structural gate checks (TOC field, blank pages, cross-references).
**Deterministic, zero hallucination, no AI, no upload.** Output in English by
default; pass `--lang zh-TW` for Traditional Chinese.

## Legal basis

| Source | Content |
|---|---|
| 化粧品產品資訊檔案管理辦法 第3條 | 16 mandatory PIF data items |
| 化粧品產品資訊檔案製作指引 | Section preparation guidance |
| TFDA implementation schedule | Phased rollout by product category (2024–2026) |

## Checks

| Check | Severity | Description |
|---|---|---|
| `section_missing` | critical | One of the 16 mandatory sections not found in the document |
| `section_empty_or_placeholder` | high | Section exists but is empty or still placeholder text |
| `section_required_keyword_missing` | high | Mandatory element missing (e.g. INCI in §3, safety in §16) |
| `section_keywords_missing` | medium | Section lacks expected regulatory keywords (heuristic) |
| `review_marker_in_section` | medium | "待補充", REVIEW, TODO, etc. — needs human confirmation |
| `safety_subrequirement_missing` | high | §16 missing signed conclusion OR SA qualification proof |
| `structure.toc_is_field` | high | TOC not a Word field |
| `structure.no_blank_pages` | medium | Suspected blank pages |
| `structure.cross_references_valid` | high | Broken cross-references |

## Usage

```bash
python -m skills.pif_audit.pif_audit pif.docx
python -m skills.pif_audit.pif_audit pif.docx --lang zh-TW
python -m skills.pif_audit.pif_audit pif.docx --fail-on high
python -m skills.pif_audit.pif_audit pif.docx --config mapping.json --mapping template_mapping.json
```

Default checklist: `examples/pif_tw/tw_pif_checklist.json`
Default mapping: `examples/pif_tw/template_mapping.json`

## Example output

```
Regulation: 化粧品產品資訊檔案管理辦法 第3條 (衛生福利部食品藥物管理署（TFDA）)
File: pif.docx
Overall: FAIL ❌ (3 issue(s), max severity: high; sections 15/16)
------------------------------------------------------------
[FAIL] section_missing  (critical)
        Section 11_stability: 11. 產品安定性試驗報告
        Mandatory section missing from document: 11. 產品安定性試驗報告
        Fix: Add the missing section per TFDA Article 3; use the PIF template heading structure.
```

## i18n

- Default output language: **English** (`en`).
- Override per run: `--lang zh-TW`, or set env `PRODOCUX_LANG`.
- Kernel returns language-neutral structured data; this skill localizes it.

## Limitations

- Keyword checks are **heuristic** — they catch obvious gaps, not legal sufficiency.
- Does not verify numerical correctness of formula totals (use Skill #7).
- Does not verify structural defects in depth without comparison (use Skill #6).
- Template heading structure must match the mapping config (PIF 標題一/二).
- .docx only.
