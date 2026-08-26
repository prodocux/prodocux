# ADR-0003: Phase 0 Kernel sidecar sink and private authentication

Status: Accepted for Phase 0 contract freeze (not implemented)

Date: 2026-08-26

## Context

Kernel HTTP `/v1` already owns deterministic request/response documents,
capability discovery, opaque `artifact://` identities, and sanitized render
error codes. The process-lifetime artifact sink is not restart-safe. The HTTP
host currently has no private service-authentication profile.

PDX Phase 0 must freeze those gaps as contracts without shipping sidecar
runtime, `/health`, `/ready`, or a filesystem sink implementation.

## Decision

1. Kernel remains the sole authority for `/v1` computation contracts: request
   and response bodies, capability and resource limits, opaque artifact
   identity (`prodocux_opaque_artifact_v1`), and the additive safe-error
   envelope defined under `docs/phase0/`.
2. The filesystem output sink is a host-injected `ArtifactSinkPort` whose
   durable identity is `artifact://` only. Record-once semantics are
   create-if-absent: identical SHA-256 is `no_op`; a different digest for the
   same identity is `conflict`. Size and media type are part of the identity
   record.
3. Sidecar filesystem layout (Phase 1): read-only root filesystem; separate
   bounded writable mounts for temporary work and the output sink. Kernel
   never accepts caller-selected output URIs, `gs://`, signed URLs, or local
   paths.
4. Private service authentication is Kernel-edge only and does not validate
   application users:
   - self-hosted: rotatable bearer token over a private network;
   - production: mTLS in addition to the same application contract.
   Request bodies are never logged.
5. Frozen compatibility manifests v1, v2, and v3 remain byte-identical.
   Phase 0 schemas live under `docs/phase0/` and are not added to those
   manifests.

## Consequences

- Phase 1 may implement the sidecar, health endpoints, bearer/mTLS profile,
  and restart-safe filesystem sink against these documents.
- Direct Kernel calls stay limited to deterministic component and contract
  tests. Product asynchronous work enters through PDX Artifact Engine.
- No WordPress, WooCommerce, OAuth, or Farpals types enter Kernel schemas.
