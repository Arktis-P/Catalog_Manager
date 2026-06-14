@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%PROJECT_ROOT%\logs" mkdir "%PROJECT_ROOT%\logs"

set "BACKEND_LOG=%PROJECT_ROOT%\logs\backend.log"
set "BACKEND_CMD=cd /d ""%BACKEND_DIR%"" && ""%VENV_PYTHON%"" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT% >> ""%BACKEND_LOG%"" 2>&1"

cscript //nologo "%~dp0_run_hidden.vbs" "cmd /c ""%BACKEND_CMD%"""
exit /b 0
