@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%VENV_PYTHON%" (
  echo [ERROR] Run scripts\setup.bat first.
  exit /b 1
)

echo Building frontend...
pushd "%FRONTEND_DIR%"
call npm run build
if errorlevel 1 (
  popd
  exit /b 1
)
popd

echo Starting production GUI server on http://127.0.0.1:%BACKEND_PORT%
start "Catalogue Manager" cmd /k "cd /d \"%BACKEND_DIR%\" && set CATALOGUE_SERVE_GUI=1 && \"%VENV_PYTHON%\" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"

set /a RETRIES=0
:WAIT_BACKEND
set /a RETRIES+=1
"%VENV_PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%BACKEND_PORT%/api/health', timeout=2)" >nul 2>&1
if not errorlevel 1 goto READY
if %RETRIES% GEQ 30 exit /b 1
timeout /t 1 /nobreak >nul
goto WAIT_BACKEND

:READY
set "APP_URL=http://127.0.0.1:%BACKEND_PORT%"
call "%~dp0open_app_window.bat" "%APP_URL%"
echo Production app running at %APP_URL%
exit /b 0
