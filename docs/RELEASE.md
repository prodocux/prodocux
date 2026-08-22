# Release policy

ProDocuX `0.3.0rc1` is the coordinated release candidate for the deterministic
document Kernel and HTTP API v1. Runtime code makes no implicit LLM calls.
The frozen `0.2.0` compatibility v1 surface remains historical evidence.

## Frozen public surface

- `GET /v1/version`
- `GET /v1/intake/capabilities`
- the five deterministic intake operations reported by that endpoint
- the packaged request, response, and capabilities schemas
- package imports `prodocux_kernel` and `api.main`

The frozen machine-readable surface is recorded in
`compatibility/pdx_prodocux_compatibility_v1.json`; the active coordinated
release-candidate surface is recorded in
`compatibility/pdx_prodocux_compatibility_v2.json`. Applications must discover
format ceilings from the capabilities endpoint rather than copy constants.

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
