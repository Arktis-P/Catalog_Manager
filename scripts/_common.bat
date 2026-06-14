@echo off
setlocal EnableExtensions

rem Resolve project root (Catalogue_Manager)
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"

set "VENV_DIR=%PROJECT_ROOT%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"
set "BACKEND_DIR=%PROJECT_ROOT%\backend"
set "FRONTEND_DIR=%PROJECT_ROOT%\frontend"
set "REQUIREMENTS=%BACKEND_DIR%\requirements.txt"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"
set "APP_URL=http://127.0.0.1:%FRONTEND_PORT%"
