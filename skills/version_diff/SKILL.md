---
name: document-version-diff
title: Document Version Diff (red-line)
version: 0.1.0
author: ProDocuX
license: MIT
tags: [word, docx, diff, redline, version, contract, review]
inputs: [.docx, .docx]
deterministic: true
llm_required: false
languages: [en, zh-TW]
---

# Document Version Diff / Red-line

Compare two Word documents and get a paragraph/table-level **added / removed /
modified** red-line. **Deterministic, runs locally, no upload, no AI.**
Output in English by default; pass `--lang zh-TW` for Traditional Chinese.

## Why

You receive a "slightly tweaked" version of a contract with no track-changes —
finding what changed means reading line by line. This tool expands paragraphs
and table rows in document order and produces a red-line in seconds.

## Usage

```bash
python -m skills.version_diff.version_diff old.docx new.docx
python -m skills.version_diff.version_diff old.docx new.docx --lang zh-TW
python -m skills.version_diff.version_diff old.docx new.docx --json
python -m skills.version_diff.version_diff old.docx new.docx --fail-on-change   # CI gate
```

## Example output

```
Old: contract_v1.docx
New: contract_v2.docx
Changes — added 1, removed 0, modified 1
------------------------------------------------------------
- Payment terms: net 30 days after signing.
+ Payment terms: net 45 days after signing.

+ This contract may be executed by electronic signature.
```

## i18n

- Default output language: **English** (`en`).
- Override per run: `--lang zh-TW`, or set env `PRODOCUX_LANG`.
- The kernel returns language-neutral structured data; this skill localizes labels.

## Limitations

- Compares **text content** (paragraphs, table rows), not styles
  (font/color/formatting).
- In-paragraph word-level edits show as a whole-paragraph replace
  (- old / + new).
- .docx only.
