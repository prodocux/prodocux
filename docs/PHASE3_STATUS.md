# Kernel Phase 3 — verified bytes retrieval (freeze)

Status: **COMPLETE** (2026-08-28).

## Formal record

Phase 3 freezes **identity-bound verified byte retrieval** for opaque
`artifact://intake|derived|sink|render/…` handles. This unblocks
Farpals `prodocux_publish_artifact`, WordPress Media Library writes,
and compare/evidence UI consumption paths.

## Freeze SHA

- Kernel Phase 3 implementation: `f6cee0d`
- Engine Phase 3 companion: `fb3aa6d`
- Phase 3 tail (compare/verify worker + `ARTIFACT_TOO_LARGE`): _(this commit)_

## Landed

- `POST /v1/artifacts/retrieve` (`prodocux_artifact_retrieve_v1` →
  `prodocux_artifact_content_v1`)
- `prodocux_kernel/rendering/artifact_retrieval.py` — namespace
  resolution, digest/size verification, 32 MiB cap
- Stable **413** `ARTIFACT_TOO_LARGE` for retrieval policy violations
- Identity **100 MiB** vs retrieval **32 MiB** layering documented
- Schemas under `docs/phase3/schemas/`
- Tests: `tests/test_phase3_retrieve.py`

## Explicitly not Phase 3 (Farpals / deployment)

- `prodocux_publish_artifact` T2 confirmation flow
- WordPress Media Library attachment creation
- Farpals `production_mtls` client certificate wiring
- Host compose / process supervision

## Legacy note

`GET /v1/render/artifacts/{artifact_id}` remains sink-only legacy;
Phase 3 consumers must use identity-bound `POST /v1/artifacts/retrieve`.

## Companion

Engine job-bound hop and compare/verify worker:
`pdx-artifact-engine/docs/PHASE3_STATUS.md`.
