@echo off
rem Shared paths for Catalogue Manager scripts.
rem Do NOT use setlocal here; this file is included via call.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%.."
set "PROJECT_ROOT=%CD%"
cd /d "%SCRIPT_DIR%"

set "VENV_DIR=%PROJECT_ROOT%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"
set "BACKEND_DIR=%PROJECT_ROOT%\backend"
set "FRONTEND_DIR=%PROJECT_ROOT%\frontend"
set "REQUIREMENTS=%BACKEND_DIR%\requirements.txt"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"
set "APP_URL=http://127.0.0.1:%FRONTEND_PORT%"
