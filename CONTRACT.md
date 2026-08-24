# ProDocuX — CONTRACT

> Version: v0.1  
> Last updated: 2026-07-28  
> Companion: `ARCHITECTURE.md`  
> This document is the technical source of truth for Kernel boundaries, APIs,
> formats, and scoring. Code or data that violate this contract break the
> evaluation setup.

---

## 0. Summary

- **Kernel (builder)** provides: deterministic tools, schemas, validation,
  document ops (invariants), render, provenance helpers, scoring, and review
  capture. **Runtime makes no implicit LLM calls.**
- **Userland (solver)** provides: profiles, prompts, mappings, dev data, and
  clients, and performs **all semantic / LLM extraction**.
- **Referee (human)** holds: held-out answers, pass criteria, model-freeze
  decisions, and contract sign-off.
- Communication: Kernel exposes `http://localhost:8900/v1`; Userland uses
  Kernel only through that API.

---

## 1. Locked decisions

| # | Decision | Content |
|---|---|---|
| 1 | Held-out answer location | Env `PRODOCUX_HELDOUT_DIR` (default in-repo `datasets/heldout/`, must stay empty / gitignored). **Kernel + referee only; solver must not read answers.** |
| 2 | Pass line (held-out) | Mandatory-field accuracy **≥ 95%** AND hallucination count **= 0** AND all L0 invariants **pass** |
| 3 | Role split | Solver = Userland / semantic side; builder = Kernel maintainers (tools/IDEs are replaceable; no machine-path binding) |

### 1.1 Extension of decision 3 (D-3a)

> **D-3a**: Kernel runtime **calls no LLM API**; all semantic extraction is done
> by the solver. Experiment records must note the frozen solver model name/version.
> - Kernel must not ship components that call LLMs; any future exception needs
>   referee approval and disclosure on `GET /v1/version`.
> - Temperature / determinism: whatever the solver side can control (else note in
>   the experiment log).

---

## 2. Boundaries

- Solver **must not** read `PRODOCUX_HELDOUT_DIR` (answers) or, when the
  experiment requires it, Kernel source.
- Builder **must not** redefine pass/fail (decision 2 belongs to the referee).
- Breaking Kernel API changes **must** bump the API version and need referee
  sign-off (they change evaluation conditions).
- Any change to the frozen model **must** be referee-approved.

---

## 3. Repositories and data

```
prodocux/                 # KERNEL (public)
  prodocux_kernel/  api/  skills/  runtime/  tests/
  CONTRACT.md  ARCHITECTURE.md  CAPABILITY_REQUESTS.md

companion-labs/           # USERLAND / external experiments (optional)
  experiments/  prototypes/

$PRODOCUX_HELDOUT_DIR/    # referee-held answers (never commit to public)
  *.json
```

Held-out hides **answers**, not inputs. Source PIFs and templates remain
visible to the solver (see §6.2).

---

## 4. Kernel API (`/v1`)

JSON over HTTP. Small intake files may use base64 (`*_b64`). Local paths are
disabled by default and are accepted only for colocated deployments when the
resolved file remains under a directory listed in
`PRODOCUX_ALLOWED_INPUT_ROOTS` (use the platform path separator). Every
response includes `kernel_version`.

### 4.0 `GET /v1/version`

```json
{
  "kernel_version": "0.3.0rc1",
  "api_version": "v1",
  "frozen_model": "<solver-side model name/version; kernel makes no LLM calls>",
  "schemas": ["pif_tw_v1"]
}
```

### 4.1 `POST /v1/extract`

Under D-3a, LLM calls happen on the solver side. Default mode: validate and
structure solver-extracted drafts + record provenance. If the referee later
moves extraction into Kernel, this endpoint performs extraction directly.

Request
```json
{
  "document_path": "….pdf",
  "profile_id": "foreign_pif_to_tw",
  "profile_version": 1,
  "extracted_draft": { "product_name": "ABC Cream", "...": "..." },
  "provenance_draft": { "product_name": {"page": 1, "snippet": "Product: ABC Cream"} }
}
```
Response
```json
{
  "kernel_version": "0.3.0rc1",
  "canonical_data": { "product_name": "ABC Cream" },
  "confidence": { "product_name": 0.97 },
  "provenance": { "product_name": {"page": 1, "snippet": "Product: ABC Cream"} },
  "validation": {
    "passed": false,
    "issues": [{"field": "cas", "rule": "cas_checksum", "severity": "error", "msg": "..."}]
  },
  "abstain_fields": ["heavy_metal_lead"]
}
```

### 4.2 `POST /v1/render`

Legacy path-shaped stub. Path-shaped bodies (`template_path` / `output_path`)
remain **501**. If the body carries `schema_version: prodocux_render_request_v1`,
the route aliases `POST /v1/render/artifact`.

### 4.2a Cloud-safe render contract (live)

Operations, additive under API `/v1`:

- `GET /v1/render/capabilities` — five formats are `available`; `requires_template`
  is `false` (Fleet/host templates are not Kernel templates).
- `POST /v1/content-blocks/validate` — product-neutral IR validation only.
- `POST /v1/render/artifact` — write `docx` / `xlsx` / `csv` / `pptx` / `pdf`
  from `prodocux_content_blocks_v1`. Artifact delivery uses a process-lifetime
  host sink (`artifact://` identity, create-if-absent). Inline delivery
  returns `content_b64` and is capped at 2 MiB decoded.
- `GET /v1/render/artifacts/{artifact_id}` — retrieve the bytes previously
  stored by this process for that identity. Tests and hosts must re-fetch and
  re-hash; a URI prefix is not proof of retrievability. Restarting the process
  drops the sink.
- `POST /v1/intake/extract-blocks` — parse a 5-format binary (`document_filename`
  + `document_b64`) into `prodocux_content_blocks_v1` plus a product-neutral
  `text_items` projection (`id`, `type`, `text`, `source_locator`) for host
  adapters. Kernel does not emit Fleet cosmetics fields.

This release **rejects** `template` (artifact or inline). Hosts map Template
Packs onto `prodocux_content_blocks_v1` before calling render. The Kernel never
accepts `gs://`, signed URLs, local paths, or caller-chosen output URIs.
Callers must not send `template_path` or `output_path`.

A6 pins are recorded in
`compatibility/pdx_prodocux_compatibility_v3.json` (byte-identical with
pdx-artifact-engine). The v3 file pins Commit A:

- ProDocuX: `fa35cb05b9c4926ecd3b56dc705a1ecacc55ac30`
- pdx-artifact-engine: `cccc9a192d1f773d5bf6b8becbe16e41e3164dd2`

Compatibility v1 and v2 remain byte-immutable. Package version stays
`0.3.0rc1`. Hosts map their own render-bundle spec onto
`prodocux_render_request_v1` before calling these routes, and must pin the
v3 commits before claiming live ProDocuX integration.

Schemas: `prodocux_content_blocks_v1`, `prodocux_render_request_v1`,
`prodocux_render_result_v1`, `prodocux_render_capabilities_v1`.

### 4.3 `POST /v1/validate-structure`

Run L0 structure invariants on a `.docx`.

`document_path` and optional `reference_path` follow the configured input-root
policy above; remote callers should use an upload/adapter flow instead of
arbitrary server filesystem paths.

### 4.4 `POST /v1/score`

Score a prediction. **Held-out mode returns aggregate scores only — never gold
answers or per-field diffs.**

### 4.5 `POST /v1/review/start` / `POST /v1/review/commit`

Capture human review → golden records (+ correction records).

### 4.6 `POST /v1/learn`

Ingest corrections → profile update suggestions (applied in Userland; referee
reviews).

### 4.7 Deterministic intake primitives

- `GET /v1/intake/capabilities` reports executable, planned, and external
  format pipelines. Storage support does not imply parsing support.
- `POST /v1/intake/profile-table` accepts an allow-root-local CSV path or small
  base64 CSV and returns `prodocux_table_profile_v1`: source checksum, columns,
  row count, and bounded preview. It performs no schedule interpretation or
  LLM call (`interpretation: none`).
- `POST /v1/intake/profile-workbook` accepts `.xlsx` and returns
  `prodocux_workbook_profile_v1`: source checksum, sheet inventory, bounded cell
  previews, formula text, and cached values when present. Legacy `.xls` is not
  accepted. It also performs no schedule interpretation.
- `POST /v1/intake/profile-document` accepts `.docx` and returns
  `prodocux_docx_profile_v1`: paragraphs/styles, headings, bounded tables,
  headers/footers, section counts, and source checksum. This is content intake;
  `/v1/validate-structure` remains the separate structure-health operation.
- `POST /v1/intake/profile-presentation` accepts `.pptx` and returns
  `prodocux_presentation_profile_v1`: slide titles/text, speaker notes, bounded
  tables, image/shape counts, and source checksum. It does not classify the
  presentation's business purpose.
- `POST /v1/intake/profile-image` accepts bounded JPEG/PNG base64, validates
  decode/media identity, and returns dimensions, orientation, size, digest,
  privacy-safe EXIF presence, truncation/review flags, and explicit OCR backend
  status. OCR is host-injected; the API does not discover local executables.

Format-specific deterministic parsers belong in `prodocux_kernel/intake`.
First-party skills may wrap them; product applications must call through `/v1`
or an adapter and must not duplicate parser implementations.

ZIP-based Office formats are preflighted before a parser opens them. The
Kernel rejects unsafe member names, encrypted entries, excessive entry counts,
more than 256 MiB declared uncompressed content, or any entry with a compression
ratio above 200:1. These are resource-safety limits, not claims that the file is
semantically valid. Entry sizes are central-directory declarations used for
preflight, not a streaming measurement of decompressed bytes. Presentation
shape counts are exact within the preview bound and explicitly marked as a
lower bound when truncated.

### 4.8 `POST /v1/verify/evidence-bundle`

Validates bounded, already-extracted typed evidence using declarative presence,
equality, numeric-range, and date/version consistency checks. Results are
deterministic and use stable pass/fail/review reason codes plus source
references. Rule selection, claim meaning, and regulatory conclusions belong
to the calling product.

### 4.9 `POST /v1/compare/normalized-profiles`

Compares bounded JSON-compatible profiles and returns stable JSON Pointer
paths, reason codes, optional source locators, and truncation disclosure.
Declared array keys enable reorder-insensitive table-row comparison. The
operation reports differences only and does not decide semantic equivalence or
business impact.

The library-level opaque artifact boundary accepts only `artifact://`
identities resolved by a host-injected resolver. It rejects network URLs and
local paths, then verifies declared media type, byte size, and SHA-256. Storage,
authorization, retention, and tenant policy remain outside the Kernel.

---

## 5. Scoring layers

| Layer | Focus | Owner | Gate |
|---|---|---|---|
| **L0** | Structure invariants | Kernel | Hard fail |
| **L1** | Field accuracy vs gold | Kernel scorer | Accuracy + hallucination |
| **L2** | Transformation policy | Kernel | Profile rules |
| **L3** | Mandatory elements present | Kernel | Missing = fail |
| **L4** | Cleanliness / aesthetics | Referee | Manual 1–5; not a gate |

**Held-out pass (decision 2):**
`L0 all pass AND mandatory_field_accuracy ≥ 0.95 AND hallucination_count == 0`.

### 5.1 L0 invariants (examples)

`toc_page_numbers_valid`, `no_blank_pages`, `cross_references_valid`,
`no_orphan_section_break`, `image_removal_no_residue`, …

---

## 6. Dev / held-out splits

### 6.1 Dev (solver-visible, includes answers)

- Location: `datasets/dev/` (gitignored JSON) or private labs `testdata/dev`
- Purpose: solver tuning (overfitting allowed)

### 6.2 Held-out (answers hidden from solver; inputs visible)

- Hidden asset is the **gold answer**, not the input files.
- Answers: `$PRODOCUX_HELDOUT_DIR` (Kernel + referee only).
- Anti-overfit rules: (1) solver never sees held-out answers; (2) `/v1/score` on
  held-out returns totals only; (3) only Kernel reads answers to score.

### 6.3 Held-out scoring flow

Solver runs on held-out inputs → `POST /v1/score` (`dataset=heldout`) → Kernel
reads `$PRODOCUX_HELDOUT_DIR` → returns totals only.

### 6.4 Phasing

- Phase A: accumulate volume; new reviewed docs go to dev.
- Phase B (~20–30 docs): carve held-out into `$PRODOCUX_HELDOUT_DIR`.

---

## 7. Data formats

### 7.1 Canonical schema (Kernel-owned)

```yaml
schema_id: pif_tw_v1
fields:
  - name: product_name
    type: string
    required: true
  - name: ingredients
    type: table
    required: true
    columns: [inci, cas, percentage, function]
```

### 7.2 Profile (Userland-owned)

```yaml
profile_id: foreign_pif_to_tw
version: 1
schema_ref: pif_tw_v1
mandatory_elements: [ingredient_table]
optional_elements: [marketing_table]
```

### 7.3 Prompt (Userland-owned)

Solver-side prompt packs; Kernel does not embed LLM prompts.

### 7.4 Golden record

```json
{
  "doc_id": "foreign_pif_001",
  "schema_ref": "pif_tw_v1",
  "model_frozen": "<solver-side model>",
  "reviewed_by": "human",
  "split": "dev",
  "fields": [{
    "field": "product_name",
    "extracted": "ABC Cream",
    "gold_value": "ABC Cream",
    "extraction_verdict": "correct",
    "template_verdict": "correct"
  }]
}
```

---

## 8. Versioning and feedback

- API `/v1`; breaking changes → `/v2` with referee sign-off.
- Kernel semantic version `MAJOR.MINOR.PATCH`.
- Within a Kernel version, freeze the engine; solvers pin the version.
- Capability ceiling: file `CAPABILITY_REQUESTS.md` → referee prioritizes →
  builder ships → solver upgrades.

---

## 9. Sign-off checklist

1. D-3a confirmed: Kernel runtime calls no LLM API.
2. §6 clarified: held-out hides **answers**; inputs stay visible to solvers.
3. Referee formal sign-off of this contract for the evaluation program.
