# Kernel Phase 3 — verified bytes retrieval (freeze)

Next coordinated release candidate: see [rc4/a4 preparation](RELEASE_RC4_A4.md).
The published versions and freeze history below are historical records.

Published version: **0.3.0rc3** (`v0.3.0rc3`; PyPI and provenance verified).

## Release-gate fixes (audit)

- Stores initialize lazily; unconfigured mounts use the process temp dir,
  not `/var/lib/prodocux`
- Intake `resolve()` no longer re-enters a non-reentrant lock
- `production_mtls` trusts only the configured verify header from
  `PRODOCUX_MTLS_TRUSTED_PEERS` (default loopback)
- Working-tree security overlay: `pypdf==6.15.0`, `fastapi==0.141.1` with
  Starlette `1.6.0`; runtime image uninstalls `pip`/`setuptools`. See
  `docs/SECURITY_RUNTIME.md`.


## Formal record

Phase 3 freezes **identity-bound verified byte retrieval** for opaque
`artifact://intake|derived|sink|render/…` handles. This unblocks
Farpals `prodocux_publish_artifact`, WordPress Media Library writes,
and compare/evidence UI consumption paths.

## Freeze SHA

- Kernel Phase 3 implementation: `f6cee0d`
- Engine Phase 3 companion: `fb3aa6d`
- Phase 3 tail (compare/verify worker + `ARTIFACT_TOO_LARGE`): `50d250a` (Kernel)

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
