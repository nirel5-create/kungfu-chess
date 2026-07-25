# Gate before pushing. Nothing is committed unless every line of this passes.
#   .\check.ps1        fast: tests + pylint (~15s) -- run between steps
#   .\check.ps1 -Full  full: adds 100% coverage + 2000-game fuzz -- run before push
param([switch]$Full)
$ErrorActionPreference = "Stop"

Write-Host "`n[tests]" -ForegroundColor Cyan
python -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "TESTS FAILED - do not push" -ForegroundColor Red; exit 1 }

Write-Host "`n[pylint (must be 10.00/10)]" -ForegroundColor Cyan
python -m pylint common
if ($LASTEXITCODE -ne 0) { Write-Host "PYLINT NOT CLEAN - do not push" -ForegroundColor Red; exit 1 }

if (-not $Full) {
    Write-Host "`nFAST OK - run .\check.ps1 -Full before pushing" -ForegroundColor Green
    exit 0
}

Write-Host "`n[coverage (must be 100%)]" -ForegroundColor Cyan
python -m pytest -q --cov=model --cov=rules --cov=realtime --cov=engine `
    --cov=input --cov=boardio --cov=texttests --cov=view --cov=common --cov=main `
    --cov-report=term --cov-fail-under=100
if ($LASTEXITCODE -ne 0) { Write-Host "COVERAGE BELOW 100% - do not push" -ForegroundColor Red; exit 1 }

Write-Host "`n[fuzz]" -ForegroundColor Cyan
$env:PYTHONPATH = "."
python tools\fuzz_game.py 2000
if ($LASTEXITCODE -ne 0) { Write-Host "FUZZ FAILED - do not push" -ForegroundColor Red; exit 1 }

Write-Host "`nALL GREEN - safe to push" -ForegroundColor Green