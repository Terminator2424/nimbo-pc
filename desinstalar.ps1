# desinstalar.ps1 - quita Nimbo (programa, accesos directos e inicio automático).
# Tus archivos NO se tocan: siguen donde estén ahora. Si quieres devolverlos, usa "Deshacer todo" ANTES de desinstalar.
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\Nimbo"
Get-Process Nimbo -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "Nimbo" -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "Nimbo.lnk") -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath("Programs")) "Nimbo.lnk") -ErrorAction SilentlyContinue
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath) {
    $clean = (($userPath -split ";") | Where-Object { $_ -and $_ -ne $InstallDir }) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $clean, "User")
}
Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Nimbo desinstalado."
$data = Join-Path $env:LOCALAPPDATA "Nimbo"
if (Test-Path $data) {
    $r = Read-Host "¿Borrar también el historial y la configuración ($data)? Sin ellos ya no podrás deshacer. [s/N]"
    if ($r -eq "s") { Remove-Item $data -Recurse -Force; Write-Host "Datos borrados." } else { Write-Host "Datos conservados." }
}
