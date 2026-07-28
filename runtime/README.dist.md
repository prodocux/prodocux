# ProDocuX Runtime

Deterministic document kernel + skills.

## Quick start

```powershell
cd <path-to-this-clone>
.\runtime\install.ps1 -Fresh
.\runtime\verify.ps1
```

See [`INSTALL.md`](INSTALL.md) for environment variables and troubleshooting.

## Contents

- `prodocux_kernel/` — deterministic doc engine
- `skills/` — CLI skills (`python -m skills.*`)
- `examples/pif_tw/` — curated synthetic fixtures
- `tests/` — pytest suite (smoke via `verify.ps1`)
