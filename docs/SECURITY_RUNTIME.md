# Runtime dependency security (working tree)

This overlay does not rewrite frozen compatibility v1/v2/v3 or the published
`0.3.0rc3` release record. It records the unpublished security floors that
replace the Phase 5 scan pins (`466dd0d` Kernel image).

## Application packages

| Package | Previous image | Working-tree floor | Reason |
|---|---|---|---|
| `pypdf` | 5.1.0 | `6.15.0` | Close PDF parser DoS / memory advisories through GHSA-fp3f-mc75-235c |
| `fastapi` | 0.115.6 | `0.141.1` | Compatible set; Starlette is pinned to `1.6.0` inside FastAPI's range |
| `starlette` | 0.41.3 (transitive) | `1.6.0` (direct pin inside FastAPI 0.141.1's `>=0.46.0` range) | Host/path URL reconstruction and form-limit advisories |

Do not pin Starlette outside the range declared by the selected FastAPI
release. The direct pin prevents resolver fallback to a vulnerable 0.4x
Starlette that still satisfies `fastapi==0.141.1`.

## Packaging tools

`pip` and `setuptools` are build/install tools. The production Dockerfile
uninstalls them after `pip install .` so they are not present in the runtime
image site-packages. Local development and wheel builds still use
`setuptools>=77` from `[build-system]`.

## Out of scope

OS/base-image packages, WordPress/plugins, and future advisories are not
cleared by this overlay. Absence of a failing functional test is not a
waiver.

Candidate SHA, isolated pip-audit, image digests, and OS disposition are in
`docs/SECURITY_CANDIDATE_EVIDENCE.md`. The formal OS/base-image acceptance
for this candidate is `docs/SECURITY_OS_ACCEPTANCE.md`. Pin Kernel
`120cbd3f1ad6fe2fb8a9263ce9000bcaaba043bb`, not a later evidence-only commit.
