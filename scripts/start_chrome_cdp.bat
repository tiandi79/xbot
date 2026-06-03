@echo off
REM Launch Chrome with CDP for xbot (calls PowerShell script)
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_chrome_cdp.ps1"
exit /b %ERRORLEVEL%
