# Formal OS / base-image acceptance — PDX candidate 120cbd3 / c82d38f

Date: 2026-08-30. Maintainer record for the unpublished Phase 5 PDX
candidate. This is not a Phase 5 completion, pin promotion, or public
release.

**Pin SHAs (unchanged by this record):**

- Kernel `120cbd3f1ad6fe2fb8a9263ce9000bcaaba043bb`
- Engine `c82d38f8d1536beb2a412241d9348d1c6ffa5651`

Do not pin this evidence commit. Frozen compatibility v1/v2/v3 and
published rc2/a2 / rc3/a3 records are unchanged.

## Scope

Accepted here: residual **OS / official `python:3.11-slim` base-image**
advisories on PDX Kernel and Engine candidate images built from the pin
SHAs above.

Not accepted here, and not waived by this record:

- Farpals Core / WordPress / plugin advisories
- Concurrent load, alerts, full-stack rollback / DB restore
- Official pin / compose / matrix promotion
- Push, tag, or PyPI publish

Farpals candidate integration (upstream suites, isolated application
audit, PHP/Docker E2E, bounded plugin rollback) **does not substitute**
for this PDX OS judgment.

## Authoritative candidate surface

Farpals rebuilds from exact git exports of the pin SHAs and the
upstream Dockerfiles. Application inventory on that surface is the
Farpals candidate audit (Kernel 35 / Engine 8 third-party packages, zero
known advisories, no skipped items; runtime pip / setuptools absent).

A local `docker build` of Engine from a dirty working tree with
`COPY . .` can also copy ignored `.tmp` developer venvs. That is **not**
the candidate surface and is not a new runtime defect in `c82d38f`.
Do not change the Engine pin to add `.dockerignore` in this cut.

## Trace

| Item | Value |
|---|---|
| Base image | `python:3.11-slim@sha256:1042b61448fef4ba92d16a8c7eb4996d027568ce64792a7877fd88511e0af7c6` |
| OS | Debian GNU/Linux 13.6 (trixie) |
| Kernel recipe SHA | `120cbd3f1ad6fe2fb8a9263ce9000bcaaba043bb` |
| Engine recipe SHA | `c82d38f8d1536beb2a412241d9348d1c6ffa5651` |
| PDX Kernel review image ID | `sha256:cf59d057f57c891dc540811096ccb7b3a032b369f8241103fa08c6a91ad5a7ba` |
| Scanner | `aquasec/trivy` image scan, MEDIUM and above |
| Application scanner | isolated `pip-audit==2.10.0` on copied site-packages |

Trivy OS package matching on the Kernel review image and on an Engine
image from the same `FROM` digest: **79** debian advisory matches, **14**
unique HIGH/CRITICAL CVE IDs, **0** Python language-package findings on
the Kernel review image. Counts are package/advisory pairs, not unique
exploits and not confirmed request-path reachability.

Supporting narrative and start-check evidence:
`docs/SECURITY_CANDIDATE_EVIDENCE.md`.

## HIGH / CRITICAL — accepted with conditions

| ID | Sev | Package / installed | Debian 13.6 fix | Acceptance |
|---|---|---|---|---|
| CVE-2026-14456 | HIGH | openssl / libssl3t64 `3.5.6-1~deb13u2` | `3.5.7-1~deb13u2` | Accept on this candidate. Sidecars serve HTTP, not QUIC. Refresh the slim digest on the next authorized rebuild. |
| CVE-2026-11822 / 11824 | HIGH | libsqlite3-0 `3.46.1-7+deb13u1` | none | Accept. Engine JobStore uses Python `sqlite3` for an internally written jobs DB and does not enable or ingest FTS5. Re-check when slim updates. |
| CVE-2026-13221, 42496, 42497, 48962, 57432, 57433, 8376, 9538 | HIGH/CRIT | perl-base `5.40.1-6` | none | Accept. Runtime CMD is Python; Archive::Tar / regex / Storable are not on the Kernel or Engine request path. |
| CVE-2025-69720 | HIGH | ncurses 6.5+20250216-2 | none | Accept. No interactive TTY application in these images. |
| CVE-2026-41992 | HIGH | gzip `1.13-1` | none | Accept. Tenant PDF parsing uses pypdf / PyMuPDF, not OS gzip. |
| CVE-2026-54369 | HIGH | libacl1 `2.3.2-2+b1` | none | Accept. Process is non-root (`pdx` 10001/10002) with constrained mounts. |

MEDIUM leftovers (glibc, pam, tar, zlib, and related) are the same
official slim baseline. Most HIGH/CRIT IDs have no Debian 13.6 backport
at scan time.

`wheel==0.46.3` remains in the runtime site-packages with no application
advisory. It is recorded, not treated as a new blocker for this
candidate.

## Maintainer decision

For candidate Kernel `120cbd3` and Engine `c82d38f` only:

1. Application-layer Phase 5 blockers (pypdf, Starlette, FastAPI, runtime
   pip / setuptools) are closed on the git-export candidate images.
2. Remaining OS / base-image advisories are **accepted** for this
   candidate with the dispositions above. They are not suppressed and
   are not a clean OS certification.
3. This acceptance does **not** clear Farpals Core / WordPress / plugin
   findings, load / alert / full rollback gates, or authorize pin
   promotion.
4. Next slim rebuild (when Debian ships fixes, or when a new PDX
   candidate is authorized) must re-scan OS packages and replace this
   record. Do not silently rebuild under the same source tags.

Recorded 2026-08-30 as the PDX maintainer OS/base-image judgment for
these pins. Functional tests and Farpals candidate E2E are not a waiver.
