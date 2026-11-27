# instalar.ps1 - compila Nimbo.exe en TU PC y lo instala para tu usuario (no pide administrador).
$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
Set-Location -LiteralPath $Here
Start-Transcript -Path (Join-Path $Here "instalacion.log") -Force | Out-Null

$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\Nimbo"
$VenvDir = Join-Path $Here ".build-venv"
$Exe = Join-Path $InstallDir "Nimbo.exe"

function Step($n, $msg) { Write-Host ""; Write-Host "[$n/6] $msg" -ForegroundColor Cyan }
function Run($file, [string[]]$ArgList) {
    & $file @ArgList
    if ($LASTEXITCODE -ne 0) { throw "Falló: $file $($ArgList -join ' ') (código $LASTEXITCODE)" }
}

function Find-Python {
    $paths = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try { $p = & py -3 -c "import sys;print(sys.executable)" 2>$null; if ($p) { $paths += $p } } catch { }
    }
    foreach ($n in "python", "python3") {
        $c = Get-Command $n -ErrorAction SilentlyContinue
        if ($c) { $paths += $c.Source }
    }
    $paths += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    $paths += Get-ChildItem "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    foreach ($p in $paths) {
        try {
            $ok = & $p -c "import sys,tkinter;print(int(sys.version_info>=(3,11)))" 2>$null
            if ($ok -eq "1") { return $p }
        } catch { }
    }
    return $null
}

try {
    # --- limpieza de la versión anterior del proyecto (se llamaba OrdenaPC); tus datos se conservan
    $Legacy = "OrdenaPC"
    Get-Process "$Legacy*" -ErrorAction SilentlyContinue | Stop-Process -Force
    Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name $Legacy -ErrorAction SilentlyContinue
    Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "$Legacy.lnk") -ErrorAction SilentlyContinue
    Remove-Item (Join-Path ([Environment]::GetFolderPath("Programs")) "$Legacy.lnk") -ErrorAction SilentlyContinue
    $legacyDir = Join-Path $env:LOCALAPPDATA "Programs\$Legacy"
    $oldPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($oldPath) {
        $kept = (($oldPath -split ";") | Where-Object { $_ -and $_ -ne $legacyDir }) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $kept, "User")
    }
    Remove-Item $legacyDir -Recurse -Force -ErrorAction SilentlyContinue

    Step 1 "Buscando Python 3.11+ (con tkinter)"
    $python = Find-Python
    if (-not $python -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "No lo encontré; lo instalo con winget (puede pedir confirmación)..."
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        $python = Find-Python
    }
    if (-not $python) {
        throw "No encontré Python 3.11+. Instálalo desde https://www.python.org/downloads/ marcando 'Add python.exe to PATH' y vuelve a ejecutar INSTALAR.bat"
    }
    Write-Host "Usando: $python"

    Step 2 "Preparando entorno de compilación (descarga las dependencias)"
    Run $python @("-m", "venv", $VenvDir)
    $vpy = Join-Path $VenvDir "Scripts\python.exe"
    Run $vpy @("-m", "pip", "install", "--upgrade", "pip", "--quiet")
    Run $vpy @("-m", "pip", "install", "-r", "requirements.txt", "pyinstaller", "--quiet")

    Step 3 "Verificando el programa (pruebas automáticas)"
    & $vpy -m unittest discover -s tests -t .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "AVISO: alguna prueba falló en tu PC. Sigo con la instalación; manda instalacion.log para revisarlo." -ForegroundColor Yellow
    }

    Step 4 "Creando Nimbo.exe (tarda unos minutos)"
    Run $vpy @("-m", "PyInstaller", "--noconsole", "--onefile", "--name", "Nimbo", "--collect-all", "customtkinter",
               "--hidden-import", "pystray._win32", "--clean", "-y", "app.py")
    $built = Join-Path $Here "dist\Nimbo.exe"
    if (-not (Test-Path $built)) { throw "No se generó dist\Nimbo.exe" }
    Write-Host "Creando Nimbo-cli.exe (para usar comandos en la terminal)..."
    Run $vpy @("-m", "PyInstaller", "--console", "--onefile", "--name", "Nimbo-cli", "--collect-all", "customtkinter",
               "--hidden-import", "pystray._win32", "-y", "app.py")
    $builtCli = Join-Path $Here "dist\Nimbo-cli.exe"
    if (-not (Test-Path $builtCli)) { throw "No se generó dist\Nimbo-cli.exe" }
    $hash = (Get-FileHash $built -Algorithm SHA256).Hash
    Write-Host "SHA-256 del ejecutable: $hash"

    Step 5 "Instalando en $InstallDir"
    Get-Process Nimbo -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 1
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Copy-Item $built $Exe -Force
    Copy-Item $builtCli (Join-Path $InstallDir "Nimbo-cli.exe") -Force
    # agrega la carpeta al PATH del usuario para poder escribir:  Nimbo-cli plan   (en una terminal NUEVA)
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    if (($userPath -split ";") -notcontains $InstallDir) {
        [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $InstallDir).TrimStart(";"), "User")
    }
    $ws = New-Object -ComObject WScript.Shell
    foreach ($lnk in @((Join-Path ([Environment]::GetFolderPath("Desktop")) "Nimbo.lnk"),
                       (Join-Path ([Environment]::GetFolderPath("Programs")) "Nimbo.lnk"))) {
        $s = $ws.CreateShortcut($lnk)
        $s.TargetPath = $Exe
        $s.WorkingDirectory = $InstallDir
        $s.Description = "Nimbo"
        $s.Save()
    }

    Step 6 "Activando el inicio con Windows y abriendo Nimbo"
    Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "Nimbo" -Value "`"$Exe`" --tray"
    Start-Process $Exe

    Write-Host ""
    Write-Host "LISTO. Nimbo quedó instalado y abierto (mira el ícono junto al reloj)." -ForegroundColor Green
    Write-Host "Empieza en modo SIMULACIÓN: no mueve nada hasta que actives 'Mover de verdad' en la pestaña Vigilante."
    Write-Host "Todo lo que mueva queda en la pestaña Historial y se puede deshacer."
    Write-Host "Para diagnosticar abre una terminal NUEVA y escribe:  Nimbo-cli doctor   y   Nimbo-cli plan"
}
catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    Stop-Transcript | Out-Null
}
