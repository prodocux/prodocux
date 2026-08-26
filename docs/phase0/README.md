# Kernel Phase 0 contracts

Additive paper contracts for the PDX sidecar profile. They are **not** a public
API, **not** listed in frozen compatibility v1/v2/v3, and **not** implemented
by this directory.

| Path | Authority |
| --- | --- |
| `schemas/` | JSON Schema Draft 2020-12 |
| `examples/` | schema-valid fixtures |
| `negative/` | documents that must fail validation |
| `limits.json` | cited `0.3.0rc2` ceilings; live values come from `/v1` |
| `fixture-digest-manifest.json` | SHA-256 of contract files (raw UTF-8 bytes, LF) |

See `docs/adr/ADR-0003-phase0-sidecar-sink-auth.md` and
`docs/PHASE0_DECISIONS.md`.
