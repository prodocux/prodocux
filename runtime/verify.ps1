# Smoke-check ProDocuX runtime after install.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Py)) {
    throw "Missing venv. Run .\install.ps1 first."
}

Push-Location $Root
try {
    Write-Host "== import checks =="
    & $Py -c "import fitz; import prodocux_kernel; import skills.doc_assemble.assemble; print('imports OK')"

    Write-Host "== prodocux_kernel version =="
    & $Py -c "import prodocux_kernel as k; print(k.__version__, k.API_VERSION)"

    Write-Host "== mapping present =="
    $mapping = Join-Path $Root "examples\pif_tw\template_mapping.json"
    if (-not (Test-Path $mapping)) { throw "Missing $mapping" }
    & $Py -c "import json; m=json.load(open(r'$mapping',encoding='utf-8')); print('sections', len(m.get('sections',[])), 'front_matter', len(m.get('front_matter',[])))"

    Write-Host "== pytest (quick) =="
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Py -m pip show pytest 2>$null | Out-Null
    $hasPytest = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prevEap
    if (-not $hasPytest) {
        & $Py -m pip install pytest==8.3.4 | Out-Null
    }
    & $Py -m pytest tests\test_doc_assemble.py tests\test_structure_health.py -q --tb=no
    if ($LASTEXITCODE -ne 0) { throw "pytest smoke failed" }

    Write-Host ""
    Write-Host "VERIFY PASS"
} finally {
    Pop-Location
}

