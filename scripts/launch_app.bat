@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%VENV_PYTHON%" (
  echo Virtual environment missing. Running setup...
  call "%~dp0setup.bat"
  if errorlevel 1 exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules" (
  echo Frontend dependencies missing. Running setup...
  call "%~dp0setup.bat"
  if errorlevel 1 exit /b 1
)

echo ========================================
echo  Catalogue Manager - Launch App
echo ========================================
echo GUI app window: %APP_URL%
echo.

echo Starting backend...
start "Catalogue Manager Backend" cmd /k ""%~dp0start_backend.bat""

echo Waiting for backend health check...
set /a RETRIES=0
:WAIT_BACKEND
set /a RETRIES+=1
"%VENV_PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%BACKEND_PORT%/api/health', timeout=2)" >nul 2>&1
if not errorlevel 1 goto BACKEND_READY
if %RETRIES% GEQ 30 (
  echo [ERROR] Backend did not become ready in time.
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto WAIT_BACKEND

:BACKEND_READY
echo Backend is ready.

echo Starting frontend...
start "Catalogue Manager Frontend" cmd /k ""%~dp0start_frontend.bat""

echo Waiting for frontend...
set /a RETRIES=0
:WAIT_FRONTEND
set /a RETRIES+=1
"%VENV_PYTHON%" -c "import urllib.request; urllib.request.urlopen('%APP_URL%', timeout=2)" >nul 2>&1
if not errorlevel 1 goto FRONTEND_READY
if %RETRIES% GEQ 30 (
  echo [ERROR] Frontend did not become ready in time.
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto WAIT_FRONTEND

:FRONTEND_READY
echo Opening GUI app window...
call "%~dp0open_app_window.bat" "%APP_URL%"
if errorlevel 1 (
  echo Could not open app window. Open this URL manually: %APP_URL%
)

echo.
echo Catalogue Manager is running.
echo   Backend : http://127.0.0.1:%BACKEND_PORT%
echo   Frontend: %APP_URL%
echo Close the Backend/Frontend terminal windows to stop the app.
exit /b 0
