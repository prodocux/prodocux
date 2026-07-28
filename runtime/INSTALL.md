# Runtime install

Clone this repository anywhere. Examples use `$PRODOCUX` for the clone root.

## Layout

| Path | Purpose |
|---|---|
| `prodocux_kernel/` | deterministic engine |
| `skills/` | CLI skills |
| `examples/pif_tw/` | curated synthetic fixtures |
| `runtime/` | install / verify helpers |
| `tests/` | pytest |

Private assets (source PDFs, Word templates, run workspaces, held-out answers)
stay **outside** this repository. Configure them with environment variables —
never commit them.

## Install

```powershell
cd $PRODOCUX
.\runtime\install.ps1 -Fresh
.\runtime\verify.ps1
```

## Environment

```powershell
$PRODOCUX = "<path-to-this-clone>"
$PY       = "$PRODOCUX\.venv\Scripts\python.exe"
# Optional private sidecars:
# $env:PRODOCUX_TW_PIF_TEMPLATE = "<private template.docx>"
# $env:PRODOCUX_SOURCE_PDF      = "<private source.pdf>"
# $env:PRODOCUX_HELDOUT_DIR     = "<private held-out answers dir>"
# $env:PRODOCUX_FORMULA_PAGES   = "<private pages.json for optional tests>"
cd $PRODOCUX
& $PY -c "import fitz; print('fitz OK')"
```

Always use `$PY` from this repo's venv for evidence / PyMuPDF runs.

## Skills example

```powershell
$run = "<private-run-workdir>"
$srcPdf = $env:PRODOCUX_SOURCE_PDF
$tpl = $env:PRODOCUX_TW_PIF_TEMPLATE

& $PY -m skills.pdf_extract.pdf_extract "$srcPdf" -o "$run\pages.json" --lang zh-TW

& $PY -m skills.doc_assemble.assemble `
  --template "$tpl" `
  --mapping "$PRODOCUX\examples\pif_tw\template_mapping.json" `
  --drafts "$run\drafts.json" `
  --pages "$run\pages.json" `
  --evidence-spec "$run\evidence_spec.json" `
  -o "$run\output.docx" `
  --evidence-index-out "$run\evidence_index.json" `
  --source-map-out "$run\source_map.json"
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No module named 'fitz'` | Use `$PY`; re-run `runtime\install.ps1 -Fresh` |
| `No module named 'prodocux_kernel'` | `cd $PRODOCUX; & $PY -m pip install -e .` |
| missing mapping | Path should be `$PRODOCUX\examples\pif_tw\` |
