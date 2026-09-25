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

## CR-001 [status: in-progress]

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
- Shipped in: not shipped
