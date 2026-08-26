# Kernel Phase 0 decision record

Status: **Phase 0 paper freeze** — Phase 1 production implementation is not
authorized by this document.

Date: 2026-08-26

## Authority

| Surface | Owner | Evidence |
| --- | --- | --- |
| HTTP `/v1` request/response | Kernel | `CONTRACT.md`, `api/main.py` |
| Capability and resource limits | Kernel | `GET /v1/intake/capabilities`, `GET /v1/render/capabilities` |
| Opaque artifact identity | Kernel | `prodocux_opaque_artifact_v1` (`artifact://` only) |
| Additive safe error envelope | Kernel | `docs/phase0/schemas/prodocux_safe_error_v1.json` |
| Filesystem output sink contract | Kernel | `docs/phase0/schemas/prodocux_filesystem_sink_record_v1.json` |
| Private service auth profile | Kernel | `docs/phase0/schemas/prodocux_sidecar_auth_profile_v1.json` |
| Run state, jobs, staging | Engine | not owned here |

## Closed Phase 1 blockers (Kernel slice)

1. Topology: Kernel is a private compute sidecar. It does not expose a second
   public Agent or Document API.
2. Schema authority: `/v1` and opaque artifact identity stay in this
   repository. Phase 0 files are additive under `docs/phase0/`.
3. Authentication: self-hosted rotatable bearer + private network;
   production mTLS without changing `/v1` application contracts.
4. Output sink: restart-safe filesystem sink on a dedicated writable mount;
   identities are `artifact://` only; record-once / idempotent create-if-absent.
5. Frozen compatibility bytes: v1/v2/v3 manifests are not edited.

## Sidecar mounts (Phase 1 target, frozen here)

| Mount | Mode | Purpose |
| --- | --- | --- |
| `/` | read-only | Kernel runtime |
| `/var/lib/prodocux/tmp` | bounded writable | ephemeral parse/render work |
| `/var/lib/prodocux/artifacts` | bounded writable | output sink bytes |

Kernel does not share a writable volume with WordPress or with Engine source
staging.

## Limit citations (do not copy into adapters as constants)

Consumers discover live ceilings from `/v1/intake/capabilities` and
`/v1/render/capabilities`. Phase 0 documents the values current as of
`0.3.0rc2` in `docs/phase0/limits.json`.

## Frozen compatibility (must remain byte-identical)

| File | SHA-256 |
| --- | --- |
| `compatibility/pdx_prodocux_compatibility_v1.json` | `0b860fc0a5693a96083de1560ff030398e762c9f0c9dc4c0975eceb1d6ca1303` |
| `compatibility/pdx_prodocux_compatibility_v2.json` | `c301aba7442b150b8186ce3b7cd8da99e9470ad0592c13f7f2818d38fd5f378e` |
| `compatibility/pdx_prodocux_compatibility_v3.json` | `9591ab363472db78efb64265e3050fa4626be43783f848d0888e732898486d2b` |

Published distribution baseline: Kernel `0.3.0rc2` tag commit
`ca165e98f3aef1c0449ebc0f5bc47ea4ebe1f5b0`. v3 implementation pin remains
`53c4784d4b2bae4437252a287193e897973e8474`.

Working-tree HEAD at Phase 0 authoring is recorded by
`tests/test_phase0_contracts.py` against the frozen manifests, not by mutating
`compatibility/pdx_prodocux_release_v1.json`.

Hackathon / prior coordinated releases remain compatible because Phase 0
adds only `docs/phase0/**` and tests. It does not edit frozen compatibility
manifests, packaged Kernel schemas, or live `/v1` operations. Phase 1 must
stay additive (ADR-0001). Wheels package `prodocux_kernel/schemas/*.json`
only.

Fixture digests: `docs/phase0/fixture-digest-manifest.json`. Algorithm: SHA-256
of each listed file's raw UTF-8 bytes as stored (LF JSON, no re-encoding).
The manifest file itself is excluded from the hashed set.

## Working-tree SHA checklist

- [x] Frozen compatibility v1 SHA-256 `0b860fc0…1303` (test-enforced)
- [x] Frozen compatibility v2 SHA-256 `c301aba7…378e` (test-enforced)
- [x] Frozen compatibility v3 SHA-256 `9591ab36…6d2b` (test-enforced)
- [x] Phase 0 fixture digest manifest present (`docs/phase0/fixture-digest-manifest.json`)
- [ ] Phase 0 contract commit SHA recorded after the contracts commit

## Explicitly out of Phase 0

- Docker sidecar, `/health`, `/ready`, bearer middleware, mTLS, filesystem
  sink implementation.
- Any edit to frozen compatibility JSON bytes.
- WordPress, WooCommerce, OAuth, or Farpals types.

## Phase 0 exit checklist

- [x] `/v1` authority confirmed; no second public API.
- [x] Filesystem sink identity is `artifact://` with SHA-256, size, media type,
      and record-once statuses `created` / `no_op` / `conflict`.
- [x] Temp/output mounts documented; root filesystem remains read-only.
- [x] Self-hosted bearer + private network and production mTLS profiles frozen.
- [x] Frozen compatibility v1/v2/v3 bytes are tested unchanged.
- [x] No application-host types in Phase 0 schemas.
- [x] Fixture digest manifest and canonical hash rule.
- [ ] Maintainer records Phase 0 commit SHA after the contracts commit.

