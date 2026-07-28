# ProDocuX runtime — one-shot install (venv + editable package + PyMuPDF check)
param(
    [switch]$Dev,
    [switch]$Fresh,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"

Write-Host "ProDocuX install -> $Root"

function Resolve-Python311 {
    param([string]$Override = "")

    if ($Override -and (Test-Path $Override)) {
        return $Override
    }

    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe"
    )

    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        $which = (Get-Command python).Source
        if ($which -notmatch "LibreOffice") { return $which }
    }

    throw @"
Python 3.11+ not found.
Install from https://www.python.org/downloads/ or pass -PythonExe 'C:\path\to\python.exe'.
Avoid LibreOffice python on PATH.
"@
}

$BasePython = Resolve-Python311 -Override $PythonExe
$ver = & $BasePython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) { throw "Cannot run $BasePython" }
$majorMinor = [version]$ver.Trim()
if ($majorMinor -lt [version]"3.11") {
    throw "Python 3.11+ required, found $($ver.Trim()) at $BasePython"
}
Write-Host "Using Python $($ver.Trim()) -> $BasePython"

if ($Fresh -and (Test-Path $Venv)) {
    Write-Host "Removing existing venv (-Fresh)..."
    Remove-Item -Recurse -Force $Venv
}

if (-not (Test-Path $Py)) {
    Write-Host "Creating venv..."
    & $BasePython -m venv $Venv
    if (-not (Test-Path $Py)) { throw "venv creation failed at $Venv" }
}

Write-Host "Installing package..."
& $Py -m pip install --upgrade pip wheel | Out-Null
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Py -m pip uninstall -y prodocux 2>$null | Out-Null
$ErrorActionPreference = $prevEap
Push-Location $Root
try {
    if ($Dev) {
        & $Py -m pip install -e ".[dev]"
    } else {
        & $Py -m pip install -e .
    }
    if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

Write-Host "Verifying PyMuPDF..."
& $Py -c "import fitz; print('fitz OK')"

Write-Host ""
Write-Host "Done. Set for this session:"
Write-Host "  `$PRODOCUX = `"$Root`""
Write-Host "  `$PY       = `"$Py`""
Write-Host ""
Write-Host "Next: .\verify.ps1"

