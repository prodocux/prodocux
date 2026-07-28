# examples/pif_tw

Curated, **synthetic** fixtures for the Taiwan PIF profile.

## Shipped (safe for public git)

| File | Role |
|---|---|
| `template_mapping.json` | 16-section TW PIF mapping |
| `01_basic_schema.json` | §1 row-label schema |
| `tw_pif_checklist.json` | pif_audit checklist |
| `evidence_spec.json` | evidence layout schema (no image binaries) |
| `sample_pages.json` | synthetic `pages.json` for pipeline tests |
| `sample_drafts_formula.json` | synthetic formula drafts |

## Not shipped (gitignored)

| Pattern | Why |
|---|---|
| `pifgen_inputs_test/` | Private extracts / evidence (never commit) |
| `_local/` | Local scratch |
| `evidence_images/` | Binary evidence dumps |

Private E2E inputs are configured via environment variables
(`PRODOCUX_TW_PIF_TEMPLATE`, `PRODOCUX_HELDOUT_DIR`, `PRODOCUX_FORMULA_PAGES`, …).
