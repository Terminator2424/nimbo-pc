@echo off
chcp 65001 >nul
title Desinstalar Nimbo
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0desinstalar.ps1"
pause
