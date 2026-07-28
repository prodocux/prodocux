---
name: number-consistency-audit
title: Number Consistency Audit
version: 0.1.0
author: ProDocuX
license: MIT
tags: [word, docx, audit, finance, invoice, contract]
inputs: [.docx]
deterministic: true
llm_required: false
languages: [en, zh-TW]
---

# Number Consistency Audit

Scan a Word document for **numeric errors**: totals that don't add up,
amount-in-words that disagrees with the digits, and mixed date formats.
**Deterministic, zero hallucination, no AI, no upload.** Output in English by
default; pass `--lang zh-TW` for Traditional Chinese.

## Why

Numeric errors are the most costly and most overlooked document defects: a total
edited by hand but never recomputed, a contract that says "twelve thousand" but
prints `21,000`, dates written `2024/1/1` in one place and `2024-01-01` in
another. Rules catch these precisely where an LLM may not.

## Checks

| Check | Severity |
|---|---|
| `table_total_mismatch` (total/subtotal row ≠ column sum) | high |
| `amount_words_mismatch` (amount in words ≠ Arabic number) | high |
| `date_format_inconsistent` (mixed date formats) | medium |

> Amount-in-words supports both Chinese capital numerals (壹萬貳仟元) and
> Arabic figures; English number words are on the roadmap.

## Usage

```bash
python -m skills.number_audit.number_audit invoice.docx
python -m skills.number_audit.number_audit *.docx --lang zh-TW
python -m skills.number_audit.number_audit contract.docx --fail-on high   # gate
```

## Example output

```
File: contract.docx
Overall: FAIL ❌ (2 issue(s), max severity: high)
------------------------------------------------------------
[FAIL] table_total_mismatch  (high)  @ Table 1, column 3
        Total row shows 5000 but the column sum is 4800 (off by 200)
        Fix: Recheck the figures or recompute the total.
[FAIL] amount_words_mismatch  (high)  @ Total: NT$ 壹萬貳仟元整（21,000）
        Amount in words "壹萬貳仟" = 12000, but the number = 21000
        Fix: Align the words and the digits to the correct amount.
```

## i18n

- Default output language: **English** (`en`).
- Override per run: `--lang zh-TW`, or set env `PRODOCUX_LANG`.
- The kernel returns language-neutral structured data; this skill localizes it.

## Limitations

- Table totals use the first row whose first cell contains a total keyword;
  complex merged cells may misfire.
- Amount-in-words compares the integer part (currency unit), not sub-units.
- .docx only (PDF/Excel planned).
