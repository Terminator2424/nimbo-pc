# Demo segura: crea archivos FALSOS, los ordena, muestra el historial y lo deshace todo.
# No toca tus archivos reales. Uso:  powershell -ExecutionPolicy Bypass -File scripts\demo-laboratorio.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
$lab = Join-Path $env:TEMP "nimbo-lab"
$db = Join-Path $env:TEMP "nimbo-lab.db"
if (Test-Path $db) { Remove-Item $db }
& $py -m nimbo lab $lab --force
& $py -m nimbo plan --layout-root $lab --db $db --settle 0 --out (Join-Path $env:TEMP "nimbo-plan.json")
& $py -m nimbo apply --layout-root $lab --db $db --settle 0 --yes --top 0
& $py -m nimbo history --db $db --limit 6
Read-Host "`nMira la carpeta $lab. Enter para DESHACER todo"
& $py -m nimbo undo --db $db --all
