# PDF backends and licensing

ProDocuX Kernel is Apache-2.0. Its default PDF writer uses ReportLab, a
permissively licensed dependency. A default installation does not install
PyMuPDF or MuPDF.

PyMuPDF is dual licensed under GNU AGPL v3 or an Artifex commercial license.
Deployments that need the optional page-rasterization backend may install it
explicitly:

```bash
pip install "prodocux[pdf-mupdf]"
```

Selecting that extra is an explicit deployment and licensing decision. It does
not change the license of ProDocuX-authored source files, but the resulting
runtime includes PyMuPDF/MuPDF and must satisfy the applicable AGPL terms or an
Artifex commercial license. Process separation is not represented as a license
exemption.

The Kernel must continue to fail clearly when a caller requires the optional
rasterizer and it is unavailable. New PDF backends must be selected through a
capability boundary and must not silently change artifact semantics.
