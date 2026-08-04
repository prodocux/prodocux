# ProDocuX — architecture overview

> Public summary for kernel v0.1.  
> Commercial plans and private lab runbooks are not in this repository.  
> Technical boundaries and APIs: see [`CONTRACT.md`](CONTRACT.md).

## What this repo is

ProDocuX Kernel is a **deterministic** document engine plus first-party skills.
Runtime **does not call any LLM API**. Semantic drafting stays on the solver side.

## Layers

| Layer | Role |
|---|---|
| Kernel (`prodocux_kernel/`) | Schemas, doc ops, render, provenance helpers, scoring, review capture |
| Skills (`skills/`) | CLI entry points for structure health, audits, assemble, PDF intake, diffs |
| Contract (`CONTRACT.md`) | API surface, scoring layers, held-out evaluation rules |
| Examples (`examples/pif_tw/`) | Synthetic TW PIF fixtures only |

## Roles (evaluation setup)

| Role | Responsibility |
|---|---|
| Referee (human) | Held-out answers, pass/fail thresholds, contract sign-off |
| Kernel builder | Deterministic engine and skills (no runtime LLM) |
| Solver | Profiles, prompts, semantic extract/draft via Kernel API |

Held-out answers live outside git (`PRODOCUX_HELDOUT_DIR`). Do not commit them.

## Flagship pipeline (deterministic)

Template extract → field mapping → precise Word write → structure repair → L0 gate.
Content drafts are supplied as `drafts.json` by the solver.

## First-party skills (shipped)

Structure health, number audit, version diff, clause diff, doc assemble,
PIF audit (TW), PDF extract, CSV table profiling, XLSX workbook profiling, and
DOCX content profiling, and PPTX presentation profiling primitives. Deterministic;
semantic schedule interpretation remains solver/userland responsibility.
