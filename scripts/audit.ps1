# Auditoría de un solo comando (Windows): estilo, tipos, seguridad, dependencias, pruebas y cobertura.
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\audit.ps1     (resultado en audit-report.txt)
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
$out = "audit-report.txt"
"Nimbo auditoría · $(Get-Date -Format s)" | Set-Content $out
& $py -m pip install --quiet ruff mypy bandit coverage pip-audit -r requirements.txt
$fail = $false
function Run($name, [scriptblock]$cmd) {
    "=== $name" | Add-Content $out
    & $cmd *>> $out
    if ($LASTEXITCODE -eq 0) { Write-Host "OK    $name" -ForegroundColor Green } else { Write-Host "FALLA $name (ver $out)" -ForegroundColor Red; $script:fail = $true }
}
Run "ruff"        { & $py -m ruff check . }
Run "ruff format" { & $py -m ruff format --check . }
Run "mypy"        { & $py -m mypy nimbo }
Run "bandit"      { & $py -m bandit -q -r nimbo -c pyproject.toml }
Run "pip-audit"   { & $py -m pip_audit -r requirements.txt }
Run "pruebas"     { & $py -m coverage run -m unittest discover -s tests -t . ; & $py -m coverage report }
if ($fail) { Write-Host "RESULTADO: hay fallas (ver $out)" -ForegroundColor Red } else { Write-Host "RESULTADO: todo en orden" -ForegroundColor Green }
