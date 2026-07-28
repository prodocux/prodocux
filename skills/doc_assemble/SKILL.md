---
name: template-document-assembler
title: Template Document Assembler
version: 0.1.0
author: ProDocuX
license: MIT
tags: [word, docx, template, assemble, toc, qa, pipeline]
inputs: [.docx, .json]
deterministic: true
llm_required: false
languages: [en, zh-TW]
---

# Template Document Assembler

Fill a Word template by **heading-anchored section replacement** (no `{{placeholders}}`),
apply deterministic structure polish, and **gate the result with L0 structural checks**
before it leaves your machine. **Deterministic, runs locally, no upload, no AI at runtime.**
Output in English by default; pass `--lang zh-TW` for Traditional Chinese.

## Model

This skill is the assembly half of the flagship pipeline. The semantic half — deciding
*what* each section should say (extraction / preference-to-data) — happens upstream in a
solver/LLM and is handed in as **language-neutral text** via a `drafts.json`. The skill
then writes deterministically and verifies structure.

```
PDF(s) ──► pages.json ──► source_map.json
                │
template.docx + mapping.json + drafts.json ──► out.docx ──► evidence images ──► L0 gate
```

Full flagship pipeline (optional intake + evidence flags):

```bash
python -m skills.doc_assemble.assemble template.docx \
    --config mapping.json --drafts drafts.json --output out.docx \
    --pdfs EU_PIF.pdf --pages-out pages.json --source-map-out source_map.json \
    --evidence examples/pif_tw/evidence_spec.json --evidence-index-out evidence_index.json \
    --toc-after 目錄 --toc-until 產品敘述 --footer-style zh --lang zh-TW
```

Or reuse pre-built pages: `--pages sample_pages.json` (skip `--pdfs`).
OCR for scanned PDFs: add `--ocr` (requires `requirements-ocr.txt` + Tesseract).

## What it does (deterministic)

| Step | Op |
|---|---|
| Locate sections | heading + heading-style anchors from `mapping.json` |
| Replace content | swap each mapped section's body for its draft lines |
| Clean pagination | remove blank page-breaks before headings; optional page-break policy via `template_rules.pagination` |
| Fit tables | clamp table widths only when `table_policy=fit_to_page`; `reuse_template_table_shape_when_possible` preserves column widths |
| Front matter | optional `front_matter` anchors in mapping + `drafts.front_matter` values |
| Label-anchored tables | `table_fill: preserve_row_labels` + `fill_mode: by_label` keeps template row labels |
| Page numbers | `PAGE`/`NUMPAGES` footer field (`--footer-style en|zh`) |
| Regenerate TOC | replace stale TOC with a fresh TOC field (`--toc-after/--toc-until`) |
| Flag review | highlight terms needing human confirmation (`--review-term`) |
| Update on open | set Word to refresh fields when the file opens |
| **Gate** | run #6 L0 invariants; non-zero exit if it fails |

## Inputs

- `mapping.json` — `template_rules` (`heading_styles`, `body_style`, `table_policy`, optional `pagination`) + `sections` + optional `front_matter`
  - `pagination.mode`: `none` | `mapped_sections_only` | `all_heading_styles` | `break_before_styles`
  - TW PIF example: `mapped_sections_only` + `chapter_break_styles: ["PIF標題一"]` (no break for §1, breaks starting at §2, and a break at each major chapter)
  - L0 validates the *policy* via `heading_pagination_matches_policy` (it does not diff against the template's static pagination)
  (`id`, `heading`, `mode`, `source_queries`). See `examples/pif_tw/template_mapping.json`.
- `drafts.json` — section content (paragraph and/or table):
  - Paragraphs: `{ "<section_id>": ["paragraph 1", ...] }`
  - Tables (e.g. §3 formula / INCI list — **required for PIF**):
    ```json
    "03_formula": {
      "table": {
        "header_rows": 1,
        "rows": [
          ["Aqua", "70.00000", "7732-18-5", "溶劑"],
          ["Alcohol denat.", "25.00000", "64-17-5", "溶劑"]
        ]
      }
    }
    ```
  See `examples/pif_tw/sample_drafts_formula.json`.

## Review marks (yellow highlight)

The assembler does **not** infer uncertainty. The solver must write marker
words into `drafts.json`; this skill only **highlights** matching text after
all content is written (kernel: `prodocux_kernel/docops/review_marks.py`).

| Step | Who | What |
|---|---|---|
| Draft | Solver | Put marker words in section text (paragraphs or table cells) |
| Assemble | This skill | Scan body + tables; paragraphs/cells containing a `--review-term` get **yellow highlight** |

**Recommended marker words** (PIF TW): `待補充`, `REVIEW`, `待確認`

```json
"02_registration": [
  "待補充：台灣產品登錄證明文件，正式交付前由輸入業者補入。",
  "CPNP reference DEMO-0000001. Source: EU PIF p.1-p.3 (synthetic demo)."
]
```

```bash
python -m skills.doc_assemble.assemble template.docx \
    --config mapping.json --drafts drafts.json --output out.docx \
    --review-term 待補充 --review-term REVIEW --review-term 待確認 \
    --lang zh-TW
```

- `--review-term` is **repeatable**; terms must **match substrings** in the final docx.
- Report field: `review_marked` / `待確認標記` (count of highlighted paragraphs/cells).
- **Not supported**: per-field `abstain` flags in JSON, auto-highlight on empty cells, or highlighting without marker text in drafts.

**Relation to `pif_audit`**: `examples/pif_tw/tw_pif_checklist.json` `review_patterns`
also detect these markers (and phrases like `未持有`). Prefer explicit `待補充` /
`REVIEW` prefixes over vague audit-trigger wording; log each item in `review.md`.

## Usage

```bash
python -m skills.doc_assemble.assemble template.docx \
    --config mapping.json --drafts drafts.json --output out.docx \
    --toc-after 目錄 --toc-until 產品敘述 \
    --footer-style zh \
    --review-term 待補充 --review-term REVIEW --review-term 待確認 \
    --lang zh-TW
```

## Example output

```
Assembled document: out.docx
Overall: PASS ✅
------------------------------------------------------------
Operations:
  Sections written: 2
  Blank page-breaks removed: 15
  Headings paged: 22
  Tables fitted to page: 13
  TOC field inserted: yes
  Review marks: 1
L0 structural gate:
  [PASS] valid_docx  (critical)
        File opens correctly
  [PASS] toc_is_field  (high)
        TOC is a Word field
  ...
```

## i18n

- Default output language: **English** (`en`).
- Override per run: `--lang zh-TW`, or set env `PRODOCUX_LANG`.
- The kernel returns language-neutral structured data; this skill localizes it.
  Invariant messages are shared with the Structure Health Check skill.

## Limitations

- The skill writes; it does **not** generate section content (that is upstream).
- TOC regeneration targets a single TOC region (`--toc-after`/`--toc-until`).
- .docx templates only.
