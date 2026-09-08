# ProDocuX Kernel 0.3.0rc5 published prerelease

Published: 2026-09-08. GitHub and PyPI publication completed successfully.

- Release source: `e09684059519c16c8ec517e8f988e440ad3c9d09`
- Tag: `v0.3.0rc5`
- Workflow run: `34213120573`
- GitHub: <https://github.com/prodocux/prodocux/releases/tag/v0.3.0rc5>
- PyPI: <https://pypi.org/project/prodocux/0.3.0rc5/>

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

The exact release source passed:

1. the complete Kernel test suite;
2. PDF regression tests for long rows, explicit lines, pagination, extraction,
   and page coordinates;
3. wheel and sdist metadata checks;
4. clean installation without a repository `PYTHONPATH`; and
5. the GitHub release asset digest gate in `.github/workflows/release.yml`.

StudioTower pin promotion is downstream work and must occur only after
`prodocux==0.3.0rc5` is publicly available and independently installable.

## Publication boundary

Immutable tag `v0.3.0rc5` points to the reviewed release commit. The GitHub
Release contains exactly the reviewed wheel and source distribution, and the
protected `pypi` environment promoted those unchanged files through Trusted
Publishing. Workflow run `34213120573` completed successfully.

Do not rewrite the published rc2, rc3, or rc4 records. Add a separate
post-publication evidence record containing the final commit, workflow URL,
asset SHA-256 values, and clean-install result. That record is
[`pdx_prodocux_release_rc5.json`](../compatibility/pdx_prodocux_release_rc5.json).

| Asset | SHA-256 |
|---|---|
| `prodocux-0.3.0rc5-py3-none-any.whl` | `58ff5622188d337ba4aa0f049eeaaa502b08e0500bc9d4d9aa045943930377d6` |
| `prodocux-0.3.0rc5.tar.gz` | `e262a3e41d174404fea3d46b9749e8fe19ae9fb477d0a73db9d82f93f5a51e32` |

A fresh environment installed the exact PyPI pin without repository path
injection. `pip check`, package version/imports, and the rendering import passed.
StudioTower must still update its own dependency pin and run its clean Docker
matrix; that downstream promotion is not implied by this upstream publication.
