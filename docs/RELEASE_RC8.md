# ProDocuX Kernel 0.3.0rc8 candidate

Status: unpublished working tree. Do not use as a package pin.

This candidate removes PyMuPDF from the default dependency set, uses ReportLab
for deterministic PDF writing, and keeps PyMuPDF page rasterization behind the
explicit `pdf-mupdf` extra. It adds a clean-install regression gate requiring
the default distribution to remain free of PyMuPDF while retaining PDF output.

No existing frozen conformance schema is changed. Publication requires license
review, clean-install verification, downstream rendering review, and a new
release approval.
