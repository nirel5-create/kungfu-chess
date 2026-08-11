# Gate before pushing. Nothing is committed unless every line of this passes.
#   .\check.ps1        fast: tests + pylint (~15s) -- run between steps
#   .\check.ps1 -Full  full: adds 100% coverage + 2000-game fuzz -- run before push
param([switch]$Full)
$ErrorActionPreference = "Stop"

Write-Host "`n[tests]" -ForegroundColor Cyan
python -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "TESTS FAILED - do not push" -ForegroundColor Red; exit 1 }

Write-Host "`n[pylint (must be 10.00/10)]" -ForegroundColor Cyan
# common/, the server package (server.py is now just its thin entry-point
# shim; the real code lives in server/) and the client package (client.py
# now lives inside it, as client/__main__.py) are ours to hold to the
# style gate. The engine/model/rules/realtime/boardio/texttests/view/input
# packages are frozen (score ~7.6) and out of scope: shipping style fixes
# into frozen code is not this project's call to make.
#
# server.py and the server package are linted in SEPARATE invocations, not
# one: pylint mis-resolves `from server.<submodule> import ...` inside the
# package when server.py (a file whose own inferred module name is also
# "server") is analysed in the very same run -- a tool quirk from the
# shim sharing its name with the package beside it, not a real import
# problem (both already score 10.00/10 analysed apart, and the server
# actually runs -- see server.py's own module docstring).
python -m pylint common server.py client
if ($LASTEXITCODE -ne 0) { Write-Host "PYLINT NOT CLEAN - do not push" -ForegroundColor Red; exit 1 }
python -m pylint server
if ($LASTEXITCODE -ne 0) { Write-Host "PYLINT NOT CLEAN - do not push" -ForegroundColor Red; exit 1 }

if (-not $Full) {
    Write-Host "`nFAST OK - run .\check.ps1 -Full before pushing" -ForegroundColor Green
    exit 0
}

Write-Host "`n[coverage (must be 100%)]" -ForegroundColor Cyan
python -m pytest -q --cov=model --cov=rules --cov=realtime --cov=engine `
    --cov=input --cov=boardio --cov=texttests --cov=view --cov=common --cov=main `
    --cov=client --cov=server `
    --cov-report=term --cov-fail-under=100
if ($LASTEXITCODE -ne 0) { Write-Host "COVERAGE BELOW 100% - do not push" -ForegroundColor Red; exit 1 }

Write-Host "`n[fuzz]" -ForegroundColor Cyan
$env:PYTHONPATH = "."
python tools\fuzz_game.py 2000
if ($LASTEXITCODE -ne 0) { Write-Host "FUZZ FAILED - do not push" -ForegroundColor Red; exit 1 }

Write-Host "`nALL GREEN - safe to push" -ForegroundColor Green