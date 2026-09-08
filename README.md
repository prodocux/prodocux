# ProDocuX Kernel

Deterministic document kernel for ProDocuX. Runtime **does not call any LLM API**
(semantic drafting stays on the solver side).

License: Apache-2.0. See [LICENSE](LICENSE).

Current prerelease on PyPI: **`0.3.0rc5`**, published from tag
**`v0.3.0rc5`** at commit `e09684059519c16c8ec517e8f988e440ad3c9d09`.

This Kernel-only release fixes deterministic PDF wrapping, explicit line
breaks, pagination, and mixed Latin/CJK font selection without changing frozen
contracts. See [rc5 publication record](docs/RELEASE_RC5.md).

```powershell
python -m pip install "prodocux==0.3.0rc5"
```

## Documents

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — public architecture overview
- [`CONTRACT.md`](CONTRACT.md) — boundaries, API, scoring contract
- [`docs/PHASE0_DECISIONS.md`](docs/PHASE0_DECISIONS.md) — Phase 0 sidecar, sink, and private-auth paper freeze
- [`CAPABILITY_REQUESTS.md`](CAPABILITY_REQUESTS.md) — capability request template
- [`docs/RELEASE.md`](docs/RELEASE.md) — release-candidate boundary and checks
- [`docs/RELEASE_RC5.md`](docs/RELEASE_RC5.md) — Kernel rc5 scope, gates, and publication boundary
- [`compatibility/pdx_prodocux_compatibility_v3.json`](compatibility/pdx_prodocux_compatibility_v3.json) — frozen additive render/extract pins and G1A render-conformance fixture digests
- [`compatibility/pdx_prodocux_release_v1.json`](compatibility/pdx_prodocux_release_v1.json) — published rc2/a2 tags, package versions, release assets, and publication status
- [`compatibility/pdx_prodocux_release_rc3_a3.json`](compatibility/pdx_prodocux_release_rc3_a3.json) — published rc3/a3 tags, package hashes, and workflow evidence; does not rewrite v1
- [`compatibility/pdx_prodocux_release_rc4_a4.json`](compatibility/pdx_prodocux_release_rc4_a4.json) — current rc4/a4 release pins, hashes, publication evidence and security boundary
- [`compatibility/pdx_prodocux_release_rc5.json`](compatibility/pdx_prodocux_release_rc5.json) — Kernel-only rc5 source pin, hashes, workflow evidence, and downstream boundary
- [`compatibility/pdx_prodocux_compatibility_v2.json`](compatibility/pdx_prodocux_compatibility_v2.json) — 0.3.0rc1 prerelease versions, operations, and schema digests
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

Install the deterministic extract/render prerelease from PyPI:

```powershell
python -m pip install "prodocux==0.3.0rc2"
```

See the
[`prodocux` PyPI `0.3.0rc2` release](https://pypi.org/project/prodocux/0.3.0rc2/)
and
[GitHub prerelease](https://github.com/prodocux/prodocux/releases/tag/v0.3.0rc2).

The older published wheel
[`prodocux` PyPI `0.3.0rc1`](https://pypi.org/project/prodocux/0.3.0rc1/)
predates the additive extract/render freeze and must not be overwritten. Frozen
compatibility v3 still pins implementation commit
`53c4784d4b2bae4437252a287193e897973e8474`. See
[`docs/RELEASE.md`](docs/RELEASE.md).

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

## Available capabilities

| Component | Endpoint | Status |
|---|---|---|
| Structure invariants (L0) | `POST /v1/validate-structure` | shipped |
| Scorer (L0–L3) | `POST /v1/score` | shipped |
| Review capture | `POST /v1/review/start`, `/commit` | shipped |
| Version | `GET /v1/version` | shipped |
| Legacy semantic extract/learn and path-shaped render | `POST /v1/extract`, `/learn`, `/render` | stub or 501 |
| Deterministic block extraction | `POST /v1/intake/extract-blocks` | shipped |
| Deterministic artifact render | `POST /v1/render/artifact` | shipped |
| Render capabilities/artifact retrieval | `GET /v1/render/capabilities`, `/artifacts/{artifact_id}` | shipped |
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
