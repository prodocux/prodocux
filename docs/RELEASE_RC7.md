# ProDocuX Kernel 0.3.0rc7 release candidate

Status: unpublished. This candidate supersedes the failed publication attempt
at public tag `v0.3.0rc6`; that tag is retained as an audit record and is not a
PyPI release or downstream pin.

The implementation is unchanged from FSF-qualified commit
`202bdcf7e987eb181ecb0ec141beb661d4c4c8df`. This follow-up changes only the
package version, release documentation, and the stale release-version test.

Scope remains PDX-P0b deterministic template conformance for DOCX, XLSX, and
PPTX. It does not implement prompt-sheet intake, close FSF-M1, or authorize
removing the FSF parser. Frozen schema bytes must remain identical to the
bilateral contract seal.

Publication requires a clean Git export of the final candidate commit to pass
the complete test suite, clean-install verification, package metadata checks,
and GitHub asset digest verification before Trusted Publishing can reach PyPI.
