# Release policy

ProDocuX `0.3.0rc2` is the coordinated prerelease that distributes the additive
deterministic extract/render surface for the document Kernel and HTTP API v1.
Runtime code makes no implicit LLM calls. The frozen `0.2.0` compatibility v1
surface remains historical evidence. Frozen v2/v3 manifests still record
surface version `0.3.0rc1`; that is the contract pin, not the live package
version.

## Frozen public surface

- `GET /v1/version`
- `GET /v1/intake/capabilities`
- the five deterministic intake operations reported by that endpoint
- the packaged intake request, response, and capabilities schemas
- package imports `prodocux_kernel` and `api.main`

Compatibility v3 adds the frozen deterministic render/extract surface:

- `GET /v1/render/capabilities`
- `GET /v1/render/artifacts/{artifact_id}`
- `POST /v1/content-blocks/validate`
- `POST /v1/render/artifact`
- `POST /v1/intake/extract-blocks`
- the packaged content-block, render request/result, and render-capability schemas

The frozen machine-readable surface is recorded in
`compatibility/pdx_prodocux_compatibility_v1.json`; the active coordinated
release-candidate base is recorded in
`compatibility/pdx_prodocux_compatibility_v2.json`. Additive render/extract
pins and G1A render-conformance fixture digests are recorded in
`compatibility/pdx_prodocux_compatibility_v3.json`. Current release tags,
versions, assets, and publication state are recorded separately in
`compatibility/pdx_prodocux_release_v1.json`. v1, v2, and v3 bytes remain
immutable; the v3 `publication_gate` is historical pre-release evidence, not
the current publication status. Applications must discover format ceilings
from the capabilities endpoint rather than copy constants.

## Git pin vs published PyPI

The already-published PyPI artifacts for `0.3.0rc1` (GitHub Release
`v0.3.0rc1`) predate the additive extract/render freeze. Those files must not be
rebuilt or re-uploaded; PyPI versions are immutable.

`0.3.0rc2` is the first PyPI prerelease that includes deterministic
extract/render. Compatibility v3 remains byte-frozen and still pins live
implementation commit
`53c4784d4b2bae4437252a287193e897973e8474` (v3 file SHA-256
`9591ab363472db78efb64265e3050fa4626be43783f848d0888e732898486d2b`).
Do not bump the public package to `0.4.0` for this additive `/v1` work.

```powershell
python -m pip install "prodocux==0.3.0rc2"
```

Asset SHA-256 digests for `v0.3.0rc2` are recorded on the GitHub Release and
must match the files promoted to PyPI.

## Change policy

- Security and correctness fixes may be backported without changing API v1
  when they preserve accepted inputs and response contracts.
- Breaking request, response, schema, operation-name, or limit-semantics
  changes require a new schema or API version.
- Product workflows, approval state, agent orchestration, and product-specific
  rules remain outside this repository.

## Release gate

1. Run the complete test suite.
2. Run `python scripts/verify_clean_install.py`.
3. Verify `tests/test_release_hygiene.py` and the compatibility manifest test.
4. Inspect the wheel outside the source tree for packaged APIs and schemas.
5. Confirm the public tree contains no credentials, private paths, generated
   customer artifacts, or product-specific runtime packages.

Tags are created only after maintainers approve the release candidate. Git
commit pins remain the authority until a tag is published.

## PyPI trusted publication

GitHub Releases are the approval boundary for package publication. The
`.github/workflows/release.yml` workflow downloads the already-approved wheel
and source archive, checks their package metadata and GitHub SHA-256 digests,
installs the tagged source in an isolated environment, and promotes the
unchanged files to PyPI. It never rebuilds a second set of files for PyPI.

Create a pending or existing-project Trusted Publisher with:

- PyPI project: `prodocux`
- GitHub owner: `prodocux`
- Repository: `prodocux`
- Workflow filename: `release.yml`
- Environment: `pypi`

Protect the `pypi` GitHub environment with a required reviewer. No long-lived
PyPI token belongs in repository secrets. Future GitHub Releases start the
workflow automatically. To promote an existing release, run **Publish release
assets to PyPI** manually with its exact tag.

`0.3.0rc2` is published at
<https://pypi.org/project/prodocux/0.3.0rc2/> from GitHub Release
<https://github.com/prodocux/prodocux/releases/tag/v0.3.0rc2>. Workflow run
`32692317376` promoted the two approved files unchanged. PyPI records one
attestation per file with repository `prodocux/prodocux`, workflow
`release.yml`, and environment `pypi`; each attestation subject digest matches
the published file.

| Asset | SHA-256 |
|---|---|
| `prodocux-0.3.0rc2-py3-none-any.whl` | `76fe43d1f1a316502af63dd8490ee47a8562b425ea5544fa3b5d81848fd1cf35` |
| `prodocux-0.3.0rc2.tar.gz` | `d3dedfba33af6bc58bf66cdc1d7d98bb2fa9e46b498b045c6573f9a5e57d987e` |

## Published rc3 overlay

`0.3.0rc3` is published from tag `v0.3.0rc3` at release commit
`466dd0de02a8cbb3834d78c9e5f91bcfe320087e`. GitHub Actions run
`33221429380` verified the release assets and promoted the unchanged files to
PyPI through the protected `pypi` environment. The GitHub, PyPI, and Integrity
API SHA-256 evidence is recorded in
`compatibility/pdx_prodocux_release_rc3_a3.json`. That overlay does not replace
`pdx_prodocux_release_v1.json`, which remains the frozen `0.3.0rc2` record.

Clean installation from the PyPI exact pin, package imports, version metadata,
and packaged render-schema smoke checks passed.

`0.3.0rc1` is published at
<https://pypi.org/project/prodocux/0.3.0rc1/>. Both files below were promoted
unchanged from GitHub Release `v0.3.0rc1`; their PyPI hashes match the approved
release assets, and PyPI records the `prodocux/prodocux`, `release.yml`,
`pypi` Trusted Publisher identity in each file's attestation.

```powershell
python -m pip install "prodocux==0.3.0rc1"
```

The approved `v0.3.0rc1` assets are:

| Asset | SHA-256 |
|---|---|
| `prodocux-0.3.0rc1-py3-none-any.whl` | `941295867b3fe1f5253e4c97220237920e26182cdfd25caabf7203e6f49afd9b` |
| `prodocux-0.3.0rc1.tar.gz` | `01120b5703bd02548438a21b1496418e3ba13916493a74c658baca6863fc81c4` |

PyPI versions are immutable. A failed or incorrectly published version must be
corrected under a new version.
