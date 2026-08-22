# ProDocuX Kernel

Deterministic document kernel for ProDocuX. Runtime **does not call any LLM API**
(semantic drafting stays on the solver side).

License: Apache-2.0. See [LICENSE](LICENSE).

Current prerelease: **`0.3.0rc1`**. It adds product-neutral evidence
verification, bounded JPEG/PNG profiling, deterministic normalized profile
diffs, and a host-injected opaque artifact boundary while preserving HTTP API
`/v1` and the frozen `0.2.0` compatibility surface.

## Documents

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — public architecture overview
- [`CONTRACT.md`](CONTRACT.md) — boundaries, API, scoring contract
- [`CAPABILITY_REQUESTS.md`](CAPABILITY_REQUESTS.md) — capability request template
- [`docs/RELEASE.md`](docs/RELEASE.md) — release-candidate boundary and checks
- [`compatibility/pdx_prodocux_compatibility_v2.json`](compatibility/pdx_prodocux_compatibility_v2.json) — active prerelease versions, operations, and schema digests
- [`compatibility/pdx_prodocux_compatibility_v1.json`](compatibility/pdx_prodocux_compatibility_v1.json) — frozen historical compatibility evidence

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

Install the published GitHub prerelease wheel with:

```powershell
python -m pip install "https://github.com/prodocux/prodocux/releases/download/v0.3.0rc1/prodocux-0.3.0rc1-py3-none-any.whl"
```

See [`runtime/INSTALL.md`](runtime/INSTALL.md) for environment variables and
private-sidecar notes.

Release maintainers can verify a wheel from an isolated temporary directory:

```powershell
python scripts/verify_clean_install.py
```

See [`docs/RELEASE.md`](docs/RELEASE.md) for the PyPI Trusted Publisher and
GitHub approval-boundary workflow.

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
| Deterministic PDF page intake | `POST /v1/intake/extract-pages` | shipped |
| JPEG/PNG technical profile | `POST /v1/intake/profile-image` | shipped |
| Typed evidence verification | `POST /v1/verify/evidence-bundle` | shipped |
| Normalized structured diff | `POST /v1/compare/normalized-profiles` | shipped |

The PDF intake endpoint accepts only a bounded base64 payload and a plain
`.pdf` basename. It returns source SHA-256, bounded page text, truncation
disclosure, and an explicit `ocr_required` status without persisting the
source document or calling an LLM.

`GET /v1/intake/capabilities` is the authoritative machine-readable source
for available intake operations and their raw-byte/page ceilings. Clients
should discover these limits instead of copying constants into adapters.

The evidence verifier accepts already-extracted typed evidence and declarative
presence, equality, numeric-range, and date/version checks. It returns stable
pass/fail/review reasons without interpreting product claims or regulations.
Image OCR is available only through an explicitly injected bounded backend;
otherwise the profile reports `ocr_unavailable`. Normalized diff reports
source-linked structural/value changes but leaves business impact to the host.

Library hosts may inject an opaque `artifact://` resolver. ProDocuX rejects
network/local-path identities at this boundary and verifies declared media
type, size, and SHA-256 before returning bytes; storage authorization and
tenant isolation remain host responsibilities.

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

## Acknowledgments

Codex and Cursor contributed implementation support, contract hardening, and
cross-review for the multi-format intake upgrade. Final design and release
decisions remain with the project maintainers.
