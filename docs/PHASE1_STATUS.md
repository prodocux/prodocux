# Kernel Phase 1 — freeze

Status: **COMPLETE** (2026-08-27).

## Formal record

PDX Phase 1 is complete for sidecar readiness, bearer and
`production_mtls` profiles, opaque artifact identity, and filesystem
persistence. Farpals interoperability is verified under the
**self-hosted private bearer** profile (loopback E2E). Verified
artifact-byte retrieval and WordPress Media Library delivery are
deferred to **Phase 3**. Production host orchestration and Farpals
client-certificate wiring remain **deployment-owned** prerequisites
(not PDX Phase 3 work).

## Freeze SHA

Recorded after this Phase 1 implementation commit (see git history /
companion Engine `docs/PHASE1_STATUS.md`).

## Landed

- `PRODOCUX_AUTH_PROFILE=self_hosted|production_mtls`
- `PRODOCUX_BEARER_TOKENS` — rotatable bearer for `/v1/*`
- `production_mtls` requires verified client cert via trusted edge
  (`SSL_CLIENT_VERIFY=SUCCESS` or private proxy cert headers). The
  verify header must not be injectable from public ingress; Kernel
  must not be publicly exposed.
- `GET /health`, `GET /ready` (`auth_profile_ok`)
- `PRODOCUX_ARTIFACT_MOUNT` — restart-safe filesystem sink
- `POST /v1/intake/materialize` → `artifact://intake/{artifact_id}/{basename}`
- `POST /v1/artifacts/derived` → `artifact://derived/{artifact_id}/{basename}`
- `POST /v1/intake/extract-blocks` — `document_b64` **or** `document_artifact`
- Sidecar `Dockerfile` (read-only root + tmp/artifacts mounts)

## Explicitly not Phase 1 / not Phase 3 (deployment backlog)

- Host compose / process supervision (Farpals deployment-owned)
- Farpals `PdxEngineClient` client-certificate wiring for
  `production_mtls` (required before production mTLS cutover; not
  Media Library work)

## Deferred to Phase 3

- Verified `artifact://…` byte retrieval
- Post-download size / digest / MIME recheck
- WordPress Media Library ingestion
- Final attachment / publication binding

Frozen compatibility manifests v1/v2/v3 remain byte-identical.
Phase 0 paper freeze SHA: `60c306a7d418cce537ca54fdd000117ae08dec6e`.
