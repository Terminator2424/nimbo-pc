@echo off
chcp 65001 >nul
title Instalador de Nimbo
cd /d "%~dp0"
echo Quitando el bloqueo de Windows a los archivos descargados...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0' -Recurse -File | Unblock-File" 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
echo.
echo (Si algo fallo, manda el archivo instalacion.log de esta carpeta)
pause
