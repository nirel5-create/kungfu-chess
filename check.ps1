# Gate before pushing. Nothing is committed unless every line of this passes.
#   .\check.ps1
$ErrorActionPreference = "Stop"

Write-Host "`n[1/3] tests" -ForegroundColor Cyan
python -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "TESTS FAILED - do not push" -ForegroundColor Red; exit 1 }

Write-Host "`n[2/3] coverage (must be 100%)" -ForegroundColor Cyan
python -m pytest -q --cov=model --cov=rules --cov=realtime --cov=engine `
    --cov=input --cov=boardio --cov=texttests --cov=main `
    --cov-report=term --cov-fail-under=100
if ($LASTEXITCODE -ne 0) { Write-Host "COVERAGE BELOW 100% - do not push" -ForegroundColor Red; exit 1 }

Write-Host "`n[3/3] fuzz" -ForegroundColor Cyan
$env:PYTHONPATH = "."
python tools\fuzz_game.py 2000
if ($LASTEXITCODE -ne 0) { Write-Host "FUZZ FAILED - do not push" -ForegroundColor Red; exit 1 }

Write-Host "`nALL GREEN - safe to push" -ForegroundColor Green
