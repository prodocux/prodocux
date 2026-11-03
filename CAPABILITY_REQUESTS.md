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

## CR-003 [status: approved]

- Reporter: source-bound verification consumer
- Date: 2026-10-31
- Public baseline: `prodocux==0.3.0rc10`
- Blocker: `verify_evidence_bundle()` checks caller-supplied values, document
  digest, and media type against declarative rules. That behavior matches its
  current contract. Locators and snippets are accepted on the request and are
  not resolved against source bytes or a Kernel-verified projection. A text
  PDF whose extracted page text contains `Subtotal: 900.00` and
  `Amount due: 1100.00` can therefore receive `pass` / `VALUES_EQUAL` for two
  supplied values of `900`, including a snippet `Amount due: 900.00` that is
  absent from the extracted text. The consumer needs an additional check that
  binds a declared value to a verified source span. This request does not
  treat the current result as a contract violation.
- Requested Kernel capability: an additive, deterministic source-bound
  evidence check. Kernel must obtain and verify the source bytes, or must
  itself verify the source identity and integrity of an immutable projection.
  A projection and digest supplied by the caller are not trusted evidence.
  The check then resolves one locator to one exact text range on that
  verified text, applies a named normalization and value conversion, and
  compares the declared value with the converted span. A pass proves only
  that the value was parsed from that span by that rule. It does not certify
  that the span is an amount due, a total, or any other business role.
  A locator plus an exact text range that identifies one span may pass even
  when the same digits appear elsewhere on the page. A search-style selector
  that does not resolve to exactly one span returns `review` or rejection,
  never `pass`. Missing text, an OCR-required page, or an unverifiable
  projection likewise cannot pass. Existing
  `prodocux_evidence_bundle_request_v1` equality, presence, range, and
  date/version checks stay semantically unchanged.
- Text and number contract: the additive contract must define the offset
  unit on the verified projection (Unicode code points), the text
  normalization applied before the span is compared (Unicode NFC and a
  declared whitespace policy), and decimal parsing that uses a canonical
  decimal string and an explicit scale. Binary floating-point values are not
  a source-bound amount representation.
- Scoring layers affected: L0, hallucination
- Required acceptance: the forged quote `Amount due: 900.00` is rejected
  against the fixture above. The real span `Subtotal: 900.00` can pass
  source binding for the value `900.00` and is not certified as the amount
  due. A correct quote with a mismatched declared value is rejected. A
  mismatch of source digest, projection identity, parser contract, or range
  is rejected. The same canonical request replays to the same result. No
  LLM call is introduced.
- Evidence: consumer probe against installed `prodocux==0.3.0rc10` on
  2026-10-31. Kernel status was `pass`, reason `VALUES_EQUAL`, claimed value
  `900`, labeled amount-due text `1100.00`, and the forged quote was absent
  from `extract_pdf_pages` output. The fixture and probe remain with the
  consumer. This request assigns no payment, model, ACL, or workflow
  behavior to Kernel.
- Referee decision: contract frozen on 2026-11-03. Product-neutral specification
  and standalone checks are in `docs/source-bound-evidence/CONTRACT.md` and
  `docs/source-bound-evidence/contract-freeze.v1.json`. This is contract approval;
  runtime implementation and release require separate authorization.
- Shipped in: not shipped
