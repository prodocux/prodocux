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
