# ProDocuX Kernel 0.3.0rc5 release candidate

Status: approved for release preparation. GitHub and PyPI publication evidence
must be recorded after the protected publication workflow succeeds.

## Scope

This Kernel-only prerelease fixes deterministic PDF rendering for StudioTower
and other consumers of `prodocux_content_blocks_v1`:

- wrap long Latin, CJK, and unbroken text within the page boundary;
- preserve explicit line breaks and blank lines;
- account for every rendered line when paginating;
- select Latin and CJK-capable built-in fonts per text run; and
- prevent silently dropped text caused by undersized fixed text boxes.

The public APIs remain `validate_content_blocks()` and
`write_content_blocks(content, target_format)`. No schema, HTTP route, Engine,
Media, or frozen compatibility record changes are included.

## Verification gates

Before publication, the exact release source must pass:

1. the complete Kernel test suite;
2. PDF regression tests for long rows, explicit lines, pagination, extraction,
   and page coordinates;
3. wheel and sdist metadata checks;
4. clean installation without a repository `PYTHONPATH`; and
5. the GitHub release asset digest gate in `.github/workflows/release.yml`.

StudioTower pin promotion is downstream work and must occur only after
`prodocux==0.3.0rc5` is publicly available and independently installable.

## Publication boundary

Create immutable tag `v0.3.0rc5` at the reviewed release commit. Attach exactly
the wheel and source distribution built from that commit. The protected `pypi`
environment must promote those unchanged files through Trusted Publishing.

Do not rewrite the published rc2, rc3, or rc4 records. Add a separate
post-publication evidence record containing the final commit, workflow URL,
asset SHA-256 values, and clean-install result.
