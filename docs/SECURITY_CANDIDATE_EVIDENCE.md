# Phase 5 PDX candidate evidence (unpublished)

This is documentation only. Frozen compatibility v1/v2/v3 and published
`pdx_prodocux_release_v1.json` / `pdx_prodocux_release_rc3_a3.json` are
unchanged. Farpals official pins must stay on the previous published SHAs
until Farpals finishes candidate integration and a separate publish approval.

**Pin these image-recipe SHAs, not this evidence commit.**

| Component | Full SHA | Message |
|---|---|---|
| Kernel | `120cbd3f1ad6fe2fb8a9263ce9000bcaaba043bb` | `test(security): align Starlette floor with the 1.6.0 pin` |
| Engine | `c82d38f8d1536beb2a412241d9348d1c6ffa5651` | `fix(security): drop pip and setuptools from the runtime image` |

`120cbd3` contains the Starlette floor test aligned to `1.6.0` (was `>=1.3.1`)
and the FastAPI table wording that matches the adopted pin. Application
floors and the pip/setuptools uninstall are already in `8be3a33`. Engine is
unchanged from `c82d38f`.

## Tests

| Suite | Result | Tree |
|---|---|---|
| Kernel `tests/test_runtime_security_floors.py` plus retrieve/PDF/compat subset | 20 passed | working tree before `120cbd3` |
| Kernel full suite | **231 passed, 10 skipped** | `120cbd3` contents |
| Engine full suite | **197 passed** (recorded on `c82d38f`; no Engine code change this cut) | `c82d38f` |

Frozen hashes still match `docs/PHASE0_DECISIONS.md`:

- `compatibility/pdx_prodocux_compatibility_v1.json` `0b860fc0…d6ca1303`
- `compatibility/pdx_prodocux_compatibility_v2.json` `c301aba7…d5f378e`
- `compatibility/pdx_prodocux_compatibility_v3.json` `9591ab36…8486d2b`

## Build method

Local Docker Desktop, `--pull=false` so the already-resolved slim digest is
reused. OCI revision is set at build time (same convention as Farpals
`build-pdx-phase3-images.ps1`). Engine is built from the Engine repository
`Dockerfile`, not `docker/pdx-engine.Dockerfile`.

```text
docker build --pull=false \
  --label org.opencontainers.image.revision=120cbd3f1ad6fe2fb8a9263ce9000bcaaba043bb \
  -t prodocux-kernel:review-120cbd3 -f Dockerfile .

docker build --pull=false \
  --label org.opencontainers.image.revision=c82d38f8d1536beb2a412241d9348d1c6ffa5651 \
  -t pdx-artifact-engine:review-c82d38f -f Dockerfile .
```

Base image (both): `python:3.11-slim@sha256:1042b61448fef4ba92d16a8c7eb4996d027568ce64792a7877fd88511e0af7c6`
(Debian GNU/Linux 13.6 / trixie).

| Image | Local tag | Image ID | OCI revision |
|---|---|---|---|
| Kernel | `prodocux-kernel:review-120cbd3` | `sha256:cf59d057f57c891dc540811096ccb7b3a032b369f8241103fa08c6a91ad5a7ba` | `120cbd3f…aba043bb` |
| Engine | `pdx-artifact-engine:review-c82d38f` | `sha256:b66bc4fff56481bd47f77ad9b009659e63725b0496b7e1eccb5500ba02e95892` | `c82d38f8…6ffa5651` |

## Start checks

Runtime images have no `pip` / `setuptools` (`importlib.util.find_spec` is
false). Isolated auditor must not install them back into the runtime.

- Kernel `GET /health` → `{"status":"ok","service":"prodocux-kernel"}`
- Engine listens on `/internal/v1/jobs`. With
  `PDX_ENGINE_AUTH_PROFILE=self_hosted` and `PDX_ENGINE_BEARER_TOKENS` set,
  `GET /ready` → `{"status":"ready","checks":{"auth_profile_ok":true}}`.
  Without bearer tokens the process still starts and correctly reports
  `not_ready` (`auth_profile_ok=false`).

Functional start is not a security-gate waiver.

## Isolated application rescan

Method: `docker cp` `/usr/local/lib/python3.11/site-packages` out of each
runtime container; scan the copy with `pip-audit==2.10.0` installed only in a
separate `python:3.11-slim` tools container (`--target /tmp/auditor`). The
runtime entrypoint is never `pip`.

| Image | pip-audit exit | Findings |
|---|---|---|
| Kernel `review-120cbd3` | 0 | No known vulnerabilities |
| Engine `review-c82d38f` | 0 | No known vulnerabilities |

Previous Phase 5 application blockers are absent: `pypdf==6.15.0`,
`starlette==1.6.0`, `fastapi==0.141.1`, and `pip` / `setuptools` are not
installed. `wheel==0.46.3` remains as a packaging leftover with no advisory;
optional future uninstall, not required to close the previous scan set.

Trivy `python-pkg` on the Kernel candidate: **0** language-package findings.

## Resolved Kernel runtime versions

Python 3.11.16. Notable pins:

| Package | Version |
|---|---|
| fastapi | 0.141.1 |
| starlette | 1.6.0 |
| pypdf | 6.15.0 |
| uvicorn | 0.34.0 |
| pydantic | 2.10.4 |
| httpx | 0.28.1 |
| PyMuPDF | 1.25.1 |
| cryptography | 50.0.1 |
| pillow | 12.3.0 |
| jsonschema | 4.26.0 |
| prodocux | 0.3.0rc3 |
| pip | **absent** |
| setuptools | **absent** |

## Resolved Engine runtime versions

Python 3.11.16. Application set: `pdx-artifact-engine==0.3.0a3`,
`jsonschema==4.26.0` plus the jsonschema transitive set (`attrs`,
`referencing`, `rpds-py`, `jsonschema-specifications`). `pip` / `setuptools`
absent. `wheel==0.46.3` present, no advisory.

## OS / base-image review

Scanner: `aquasec/trivy:latest` against `prodocux-kernel:review-120cbd3`,
severities MEDIUM and above. Engine uses the same `FROM` digest, so the OS
set is the official slim baseline rather than an Engine-specific overlay.

| Class | Count |
|---|---|
| OS packages (debian 13.6) | 79 advisory matches |
| Unique HIGH/CRITICAL CVE IDs | 14 |
| Python language packages | 0 |

This is package/advisory matching, not an exploitability proof. Absence of a
failing functional test is not a waiver. WordPress/plugins are Farpals-owned
and were not scanned here.

### HIGH / CRITICAL disposition

| ID | Sev | Package | Fix in Debian 13.6 | Maintainer decision |
|---|---|---|---|---|
| CVE-2026-14456 | HIGH | openssl / libssl3t64 3.5.6 | `3.5.7-1~deb13u2` | QUIC-server unbounded memory. These sidecars serve HTTP, not QUIC. Refresh the slim digest on the next rebuild; not an application-dep blocker. |
| CVE-2026-11822 / 11824 | HIGH | libsqlite3-0 3.46.1 | none | FTS5 / heap issues. Engine JobStore uses Python `sqlite3` for an internally written jobs DB and does not enable or ingest FTS5. No Debian fix yet. Accept on this candidate; re-check when slim updates. |
| CVE-2026-13221, 42496, 42497, 48962, 54369-adjacent perl set, 57432, 57433, 8376, 9538 | HIGH/CRIT | perl-base 5.40.1-6 | none | Leftover Debian essential. Runtime CMD is Python; Archive::Tar / regex / Storable paths are not on the Kernel/Engine request path. |
| CVE-2025-69720 | HIGH | ncurses | none | No interactive TTY application in these images. |
| CVE-2026-41992 | HIGH | gzip | none | OS compressor; not used to parse tenant PDFs (that path is pypdf/PyMuPDF). |
| CVE-2026-54369 | HIGH | libacl1 | none | Symlink traversal in libacl helpers. Process is non-root (`pdx` 10001/10002) with constrained mounts. |

MEDIUM leftovers are the same official slim baseline (glibc, pam, tar, zlib,
and related). No maintained backport is available for most of the HIGH/CRIT
set in Debian 13.6 at scan time.

**Decision:** application Python findings that blocked Phase 5 are closed on
these candidate images. OS/base-image advisories remain and are inherited
from `python:3.11-slim`. They are recorded, not suppressed. They do not
authorize rewriting frozen records or promoting Farpals official pins.

## Out of scope (Farpals line)

- Changing official `phase3-pins.json`, compose, or compatibility matrix
- Repairing `audit-phase5-dependencies.ps1` / `test-phase5-upstream.ps1` so
  they do not require runtime pip
- Candidate `-PinsPath`, PHP/Docker E2E, rollback/load, WordPress/plugin scan
- Push, tag, or PyPI publish
