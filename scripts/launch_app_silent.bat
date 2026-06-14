@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%VENV_PYTHON%" (
  cscript //nologo "%~dp0_run_hidden.vbs" "cmd /c ""%~dp0setup.bat"""
  if errorlevel 1 exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules" (
  cscript //nologo "%~dp0_run_hidden.vbs" "cmd /c ""%~dp0setup.bat"""
  if errorlevel 1 exit /b 1
)

if not exist "%PROJECT_ROOT%\logs" mkdir "%PROJECT_ROOT%\logs"

call "%~dp0start_backend_hidden.bat"
call "%~dp0start_frontend_hidden.bat"

set /a RETRIES=0
:WAIT_BACKEND
set /a RETRIES+=1
"%VENV_PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%BACKEND_PORT%/api/health', timeout=2)" >nul 2>&1
if not errorlevel 1 goto BACKEND_READY
if %RETRIES% GEQ 45 exit /b 1
timeout /t 1 /nobreak >nul
goto WAIT_BACKEND

:BACKEND_READY
set /a RETRIES=0
:WAIT_FRONTEND
set /a RETRIES+=1
"%VENV_PYTHON%" -c "import urllib.request; urllib.request.urlopen('%APP_URL%', timeout=2)" >nul 2>&1
if not errorlevel 1 goto FRONTEND_READY
if %RETRIES% GEQ 45 exit /b 1
timeout /t 1 /nobreak >nul
goto WAIT_FRONTEND

:FRONTEND_READY
call "%~dp0open_app_window.bat" "%APP_URL%"
exit /b 0
