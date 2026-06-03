@echo off
REM One-click: python run.py
cd /d "%~dp0.."
call .venv\Scripts\activate.bat 2>nul
python run.py %*
exit /b %ERRORLEVEL%
