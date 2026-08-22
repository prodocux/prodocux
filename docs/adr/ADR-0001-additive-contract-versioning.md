# ADR-0001: Preserve frozen contracts through additive versioning

Status: Accepted for implementation

Date: 2026-08-22

## Context

ProDocuX 0.2.0 and PDX Artifact Core 0.2.0a2 share a release-candidate
compatibility manifest. Existing applications pin those versions and schema
digests. New deterministic intake and evidence operations must not make an old
contract appear to have changed after publication.

The PDX repository fixed three schema digests in commit `61cff57` after
enforcing LF endings for JSON. ProDocuX retained the pre-fix digest values.
Before freezing the surface, ProDocuX synchronizes those three digest entries
without changing any schema. The resulting v1 manifest SHA-256 is
`0b860fc0a5693a96083de1560ff030398e762c9f0c9dc4c0975eceb1d6ca1303` in
both repositories.

## Decision

1. The synchronized `pdx_prodocux_compatibility_v1.json` is immutable.
2. Tests pin the v1 manifest byte digest and validate only schemas explicitly
   listed by that manifest.
3. Existing v1 schema files are never edited for additive capability work.
4. A new operation receives a new request/result schema and may remain under
   HTTP API `/v1` only when existing operations and accepted documents are
   unchanged.
5. The next coordinated release publishes
   `pdx_prodocux_compatibility_v2.json`; v1 remains packaged as historical
   compatibility evidence.
6. Breaking request, response, or semantic changes require a new contract or
   API version.

## Consequences

- Old consumers can continue validating their exact pinned surface.
- Adding a schema no longer causes the v1 manifest test to demand an in-place
  manifest mutation.
- Active-release tests must target v2 once v2 is populated; they must not infer
  the active surface from every JSON file found in the package.
- JSON files use LF endings so byte digests are stable across supported
  platforms.
