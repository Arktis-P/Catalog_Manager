@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%PROJECT_ROOT%\logs" mkdir "%PROJECT_ROOT%\logs"

set "FRONTEND_LOG=%PROJECT_ROOT%\logs\frontend.log"
set "FRONTEND_CMD=cd /d ""%FRONTEND_DIR%"" && npm run dev -- --host 127.0.0.1 --port %FRONTEND_PORT% >> ""%FRONTEND_LOG%"" 2>&1"

cscript //nologo "%~dp0_run_hidden.vbs" "cmd /c ""%FRONTEND_CMD%"""
exit /b 0
