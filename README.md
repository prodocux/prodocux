# ProDocuX Kernel

Deterministic document kernel for ProDocuX. Runtime **does not call any LLM API**
(semantic drafting stays on the solver side).

License: Apache-2.0. See [LICENSE](LICENSE).

## Documents

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — public architecture overview
- [`CONTRACT.md`](CONTRACT.md) — boundaries, API, scoring contract
- [`CAPABILITY_REQUESTS.md`](CAPABILITY_REQUESTS.md) — capability request template

## Install

```powershell
git clone https://github.com/prodocux/prodocux.git
cd prodocux
.\runtime\install.ps1 -Fresh
.\runtime\verify.ps1
```

Or:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

See [`runtime/INSTALL.md`](runtime/INSTALL.md) for environment variables and
private-sidecar notes.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Start API

```powershell
.\.venv\Scripts\python.exe run_kernel.py   # http://localhost:8900/v1
```

## P1 delivered

| Component | Endpoint | Status |
|---|---|---|
| Structure invariants (L0) | `POST /v1/validate-structure` | shipped |
| Scorer (L0–L3) | `POST /v1/score` | shipped |
| Review capture | `POST /v1/review/start`, `/commit` | shipped |
| Version | `GET /v1/version` | shipped |
| Semantic extract/render/learn | — | 501 (later) |

## Flagship pipeline

Deterministic template extract → field mapping → precise write → structure repair → L0 gate.
Content drafts are supplied by the solver as `drafts.json`.

See `examples/pif_tw/` for curated **synthetic** fixtures (no customer documents).

## Skills (first-party)

| Skill | Module |
|---|---|
| Structure health | `skills.structure_health` |
| Number audit | `skills.number_audit` |
| Version diff | `skills.version_diff` |
| Clause diff | `skills.clause_diff` |
| Doc assemble | `skills.doc_assemble` |
| PIF audit (TW) | `skills.pif_audit` |
| PDF extract | `skills.pdf_extract` |

All first-party skills are deterministic. CLI messages support `en` and `zh-TW`.
