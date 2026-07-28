---
name: multi-document-clause-diff
title: Multi-document Clause Diff
version: 0.1.0
author: ProDocuX
license: MIT
tags: [word, docx, contract, clause, diff, legal, compare]
inputs: [.docx, .docx, ...]
deterministic: true
llm_required: false
languages: [en, zh-TW]
---

# Multi-document Clause Diff

Compare **two or more** Word contracts/SOPs and see exactly **which clauses
differ or are missing** across versions — aligned by clause number
(`第X條` / `Article N` / `Section N` / `1.2.3`).
**Deterministic, runs locally, no upload, no AI.** Output in English by
default; pass `--lang zh-TW` for Traditional Chinese.

## Why

When you receive several "slightly edited" versions of the same contract,
finding what actually changed clause-by-clause is slow and error-prone.
This tool aligns clauses by their numbering and flags `DIFFERS` /
`MISSING in some` deterministically — no model guessing.

## Usage

```bash
python -m skills.clause_diff.clause_diff v1.docx v2.docx
python -m skills.clause_diff.clause_diff v1.docx v2.docx v3.docx --lang zh-TW
python -m skills.clause_diff.clause_diff a.docx b.docx --json
python -m skills.clause_diff.clause_diff a.docx b.docx --fail-on-diff   # CI gate
```

## Example output

```
Clause comparison across 2 documents
Documents: v1.docx, v2.docx
Same: 3  Differs: 1  Missing in some: 1
------------------------------------------------------------
[DIFFERS] Clause 第3條
    v1.docx: 第3條 付款條件：簽約後30日內付清。
    v2.docx: 第3條 付款條件：簽約後45日內付清。

[MISSING in some] Clause 第6條
    v1.docx: (absent)
    v2.docx: 第6條 本合約得以電子簽章方式簽署。
```

## i18n

- Default output language: **English** (`en`).
- Override per run: `--lang zh-TW`, or set env `PRODOCUX_LANG`.
- The kernel returns language-neutral structured data; this skill localizes it.

## Limitations

- Clauses are aligned by their **leading clause number**; documents without
  clause numbering fall back to no alignment.
- Compares **text content**, not styles (font/color/formatting).
- .docx only.

## Who it's for

Legal, procurement, editors, and QA teams (SOP revisions).
