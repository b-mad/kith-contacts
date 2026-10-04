@echo off
rem Double-click to stop Contact Manager. Your contacts and backups are kept.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0program\deploy\windows\stop.ps1"
