---
name: pdf-page-extract
title: PDF Page Text Extraction
version: 0.1.0
author: ProDocuX
license: MIT
tags: [pdf, intake, extraction, provenance, pif]
inputs: [.pdf, source_pages.txt]
outputs: [pages.json]
deterministic: true
llm_required: false
languages: [en, zh-TW]
capability_request: CR-001
---

# PDF Page Text Extraction (CR-001)

Deterministic per-page text extraction from PDF sources. Produces standard
`pages.json` with `{file, page, text}` records, engine metadata, and file
hashes — for `map_sources_to_sections`, provenance, and held-out evaluation.

**Not an LLM capability.** This is input-prep; semantic mapping/drafting stays
on the solver / operator side.

## Output schema (`prodocux_pages_v1`)

```json
{
  "schema": "prodocux_pages_v1",
  "engine": "pypdf",
  "engine_version": "5.x",
  "source_files": [{"path": "...", "file": "EU.pdf", "sha256": "...", "page_count": 35}],
  "pages": [{"file": "EU.pdf", "page": 1, "text": "...", "char_count": 1234}]
}
```

## Usage

```bash
python -m skills.pdf_extract.pdf_extract report.pdf --out pages.json
python -m skills.pdf_extract.pdf_extract *.pdf --out pages.json
python -m skills.pdf_extract.pdf_extract --from-source-pages source_pages.txt -o pages.json
python -m skills.pdf_extract.pdf_extract report.pdf --lang zh-TW --json
```

## Dev bridge

`--from-source-pages` imports PIFaudit-style `source_pages.txt` (headers like
`=== file.pdf | Page 1 ===`) when PDFs are not available. For held-out / L1
scoring, use the same `pypdf` extraction path, not ad-hoc scripts.

## OCR (optional)

```bash
pip install -r requirements-ocr.txt   # + system Tesseract
python -m skills.pdf_extract.pdf_extract scan.pdf -o pages.json --ocr
```

## Related

- Evidence page rendering / embedded images: `intake/pdf_images.py` + `examples/pif_tw/evidence_spec.json`
- Full pipeline: `skills/doc_assemble` with `--pdfs`, `--pages`, `--evidence`

## Limitations

- Scanned PDFs need `--ocr` and Tesseract installed.
- Evidence injection is via `doc_assemble --evidence`, not this skill alone.
- Engine versions recorded in output for reproducibility.
