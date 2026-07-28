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

Public history is intentionally empty. Completed capability work is reflected in
code, tests, and release notes — not in a private collaboration log.
