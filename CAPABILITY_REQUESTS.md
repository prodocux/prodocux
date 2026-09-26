# CAPABILITY_REQUESTS — Kernel capability requests

> When the solver hits a Kernel capability ceiling, open a request here.
> Rules: `CONTRACT.md` §8. Filing a request does **not** mean immediate implementation;
> Kernel versions stay frozen within a release until the referee approves a change.

## Status

- `proposed` — filed, awaiting referee decision
- `approved` — approved, awaiting Kernel implementation
- `in-progress` — being implemented
- `done` — shipped (note Kernel version)
- `rejected` — declined (note reason)

## Template

```md
## CR-XXX [status: proposed]
- Reporter:
- Date:
- Blocker: (dataset / document / field / observed failure)
- Requested Kernel capability:
- Scoring layers affected: (L0 / L1 / L2 / L3 / hallucination)
- Evidence: (run notes or scores)
- Referee decision:
- Shipped in:
```

## Open / closed requests

Completed capability work is reflected in code, tests, and release notes — not
in a private collaboration log.

## CR-001 [status: done]

- Reporter: bounded local-index consumer
- Date: 2026-09-25
- Blocker: `prodocux==0.3.0rc8` returns `truncated=true` after the bounded
  `prodocux_content_blocks_v1` projection for a DOCX containing more than 200
  addressable headings, but supplies no total block count, omitted range, or
  continuation cursor. A unique marker after the bound is therefore absent
  from the returned projection. The consumer can only report
  `partial_unknown`; it cannot safely complete the projection.
- Requested Kernel capability: an additive, deterministic, bounded and
  continuable content-block projection. Every response should bind the source
  digest and parser contract version, identify a deterministic cursor or
  explicit non-overlapping range, disclose processed and known-total counts
  when knowable, report omitted or unsupported content classes and parser
  warnings, and distinguish complete, partial-known and partial-unknown
  coverage. Completed ranges must be reconstructable without duplicated or
  missing addressable blocks; source mutation must invalidate continuation.
  Existing `prodocux_content_blocks_v1` callers must remain compatible.
- Scoring layers affected: L0, hallucination
- Evidence: reproducible rc8 test with 206 DOCX headings; heading 206 contains
  a unique tail marker. The response is truncated, exposes 200 bounded blocks,
  and provides neither a known total nor continuation information. This
  request intentionally does not prescribe storage, search, ACL, embedding,
  memory, UI, or product workflow behavior.
- Referee decision: approved for implementation on 2026-09-25; release remains
  separately gated.
- Shipped in: `prodocux==0.3.0rc9`

## CR-002 [status: in-progress]

- Reporter: bounded local-index consumer
- Date: 2026-09-26
- Blocker: `prodocux==0.3.0rc9` has format-specific source and projection
  ceilings. DOCX block continuation exists, but PDF over 50 pages is rejected
  as `REQUEST_INVALID`, and other formats can clip rows, columns, blocks,
  shapes, tables, text, OCR regions or source bytes without a common way to
  continue. A versioned 55-page PDF fixture publishes zero projection state,
  so its page-55 marker cannot be indexed or retrieved. Increasing one limit
  would only move the failure boundary.
- Requested Kernel capability: an additive, deterministic, cross-format
  bounded-projection envelope with format-owned range profiles. Every response
  must bind source digest, media type and parser-contract name/version; state a
  half-open range and stable next-range descriptor; disclose processed and
  known-total counts when provable, omissions/warnings/OCR disposition, and
  complete/partial-known/partial-unknown coverage; replay deterministically;
  and fail closed on gaps, overlaps, descriptor mismatch or source mutation.
  Required profiles are: DOCX block plus table/text subrange where clipping can
  occur; PDF page plus page-text/OCR clipping disclosure; CSV row with fixed
  header binding; XLSX sheet plus row/column binding; PPTX slide plus
  shape/table/text coverage. Image inputs must expose stable terminal source,
  pixel, OCR-region and text limits; tile/region continuation is required only
  if Kernel can preserve deterministic identity and coverage. Source-byte
  ceilings are a separate contract: Kernel must either support artifact-backed
  bounded/random access or return a stable `SOURCE_TOO_LARGE` terminal result.
  Projection limits must return a stable continuation-required disposition,
  never generic invalid-request and never a successful undisclosed prefix.
- Scoring layers affected: L0, L1, hallucination
- Evidence: external consumer records public rc9 limits and executable
  DOCX/PDF vectors.
  The 206-heading DOCX proves the current 200+6 continuation path. The 55-page
  PDF is rejected at the 50-page ceiling with zero source versions,
  projections, blocks and FTS rows. Completion requires versioned tail-marker
  fixtures for DOCX, PDF, CSV, XLSX, PPTX and supported image behavior. Each
  fixture must either reconstruct the complete ordered projection without
  duplication/loss or produce a declared, deterministic non-continuable
  terminal result. Existing public callers and frozen contracts remain
  compatible through additive versioning. This request does not assign FTS,
  ACL, citation, memory, scheduling or durable workflow semantics to Kernel.
- Referee decision: approved for implementation on 2026-09-26; contract freeze
  and release remain separately gated.
- Shipped in: not shipped
