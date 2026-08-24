# ADR-0002: Cloud-safe render artifact contract

Status: Accepted for A0 implementation

Date: 2026-08-23

## Context

`POST /v1/render` is a 501 stub whose historical request shape used local
`template_path` / `output_path` values. That shape is not safe for hosted
execution. Render must stay product-neutral: Kernel code must not learn
domain-specific document semantics, while first-party skills/examples may
continue to ship optional domain packages.

Opaque artifact identities already exist as `artifact://` only. Storage object
identities such as `gs://` belong to the host/PDX layer, never Kernel requests.

## Decision

1. Leave `POST /v1/render` as a 501 stub. Do not revive path-based render.
2. Add `GET /v1/render/capabilities`, `POST /v1/content-blocks/validate`, and
   `POST /v1/render/artifact`.
3. Kernel render I/O uses `artifact://` identities plus bounded inline bytes.
   Hosts inject `ArtifactResolverPort` and `ArtifactSinkPort`. The HTTP host
   uses a process-lifetime sink and exposes `GET /v1/render/artifacts/{artifact_id}`
   so identities can be resolved in-process. The sink assigns output URIs
   (create-if-absent; conflicting digest fails closed). Callers supply only
   `output_name` and `delivery_mode`. This release rejects `template`; hosts map
   Template Packs to content blocks until a resolver-backed template renderer
   exists.
4. Content blocks are a product-neutral IR. Domain packs stay outside
   `prodocux_kernel/rendering`.
5. Compatibility v1 and v2 manifests are immutable. A later A6 freeze publishes
   compatibility v3 after a two-commit provenance sequence. A0 does not write
   v3 or self-referential git SHAs.
6. A0 does not invoke format writers. Capabilities mark all five formats
   `planned` and `POST /v1/render/artifact` returns `RENDERER_NOT_AVAILABLE`
   after contract validation.

## Update (A6, 2026-08-24)

Commit A `fa35cb05b9c4926ecd3b56dc705a1ecacc55ac30` landed live extract and
five-format writers. Decision 6 applied only to the A0 draft window.
This freeze publishes `compatibility/pdx_prodocux_compatibility_v3.json`
pinning that commit and pdx-artifact-engine Commit A
`cccc9a192d1f773d5bf6b8becbe16e41e3164dd2`. Decisions 1–5 remain.

## Consequences

- Hosted callers can integrate against a stable fail-closed contract before
  any renderer exists.
- Existing path-shaped clients continue to receive 501 on `/v1/render`.
- PDX reuses ToolRequest / ToolResult / receipt schemas; it does not add
  format-specific Core contracts for render.
