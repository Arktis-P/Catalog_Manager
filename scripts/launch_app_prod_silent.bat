@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%VENV_PYTHON%" (
  echo [ERROR] Run scripts\setup.bat first.
  exit /b 1
)

if not exist "%PROJECT_ROOT%\logs" mkdir "%PROJECT_ROOT%\logs"

echo Building frontend...
pushd "%FRONTEND_DIR%"
call npm run build
if errorlevel 1 (
  popd
  exit /b 1
)
popd

set "BACKEND_LOG=%PROJECT_ROOT%\logs\backend.log"
set "BACKEND_CMD=cd /d ""%BACKEND_DIR%"" && set CATALOGUE_SERVE_GUI=1 && ""%VENV_PYTHON%"" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT% >> ""%BACKEND_LOG%"" 2>&1"
cscript //nologo "%~dp0_run_hidden.vbs" "cmd /c ""%BACKEND_CMD%"""

set "APP_URL=http://127.0.0.1:%BACKEND_PORT%"
set /a RETRIES=0
:WAIT_BACKEND
set /a RETRIES+=1
"%VENV_PYTHON%" -c "import urllib.request; urllib.request.urlopen('%APP_URL%/api/health', timeout=2)" >nul 2>&1
if not errorlevel 1 goto READY
if %RETRIES% GEQ 45 exit /b 1
timeout /t 1 /nobreak >nul
goto WAIT_BACKEND

:READY
call "%~dp0open_app_window.bat" "%APP_URL%"
exit /b 0
